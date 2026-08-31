"""subagent 测试：task 工具 + Agent._spawn_subagent 的委托、隔离、上限、权限。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from coding_agent.agent import Agent
from coding_agent.config import AgentConfig
from coding_agent.errors import MaxStepsExceeded, ToolError
from coding_agent.llm.client import ChatResponse, ToolCall
from coding_agent.messages import Conversation
from coding_agent.tools import TASK, ToolContext, build_default_registry


class ScriptedClient:
    """按脚本依次返回 ChatResponse 的假客户端，记录每次调用的 messages 与 tools。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []
        self.tool_sets: list[list[dict]] = []

    def chat(self, messages, tools=None, on_text=None):
        self.calls.append(messages)
        self.tool_sets.append(tools or [])
        resp = self.responses.pop(0)
        if on_text and resp.content:
            on_text(resp.content)
        return resp


def tc(id, name, arguments):
    return ToolCall(id=id, name=name, arguments=arguments)


def resp(content="", tool_calls=None, finish_reason="tool_calls"):
    return ChatResponse(content=content, tool_calls=tool_calls or [], finish_reason=finish_reason)


def make_agent(tmp_path, client, max_steps=10, max_failures=3, subagent_max_steps=5):
    config = AgentConfig(
        max_steps=max_steps, max_failures=max_failures, subagent_max_steps=subagent_max_steps
    )
    return Agent(
        config,
        client,
        build_default_registry(),
        Conversation(system_prompt="sys"),
        ToolContext(workdir=tmp_path),
    )


# --------------------------------------------------------------------------- #
# task 工具
# --------------------------------------------------------------------------- #


def test_task_registered_in_default_registry():
    assert "task" in build_default_registry().names()


def test_task_handler_delegates_and_returns_result():
    c = ToolContext()
    c.spawn_subagent = lambda prompt: f"done: {prompt}"
    assert TASK.handler({"prompt": "review foo.py"}, c) == "done: review foo.py"


def test_task_missing_prompt():
    c = ToolContext()
    with pytest.raises(ToolError, match="prompt"):
        TASK.handler({}, c)


def test_task_without_spawner():
    c = ToolContext()  # spawn_subagent 为 None
    with pytest.raises(ToolError, match="不可用"):
        TASK.handler({"prompt": "x"}, c)


def test_registry_without_removes_only_target():
    reg = build_default_registry()
    sub = reg.without("task")
    assert "task" not in sub.names()
    assert "read_file" in sub.names()
    assert "task" in reg.names()  # 原注册表不受影响


# --------------------------------------------------------------------------- #
# _spawn_subagent 行为
# --------------------------------------------------------------------------- #


def test_spawn_subagent_returns_conclusion_isolated_no_task(tmp_path):
    client = ScriptedClient([
        resp(tool_calls=[tc("c1", "list_dir", '{"path": "."}')]),
        resp(content="子任务完成", tool_calls=None, finish_reason="stop"),
    ])
    conv = Conversation(system_prompt="sys")
    conv.add_user("主任务的一些历史")
    agent = Agent(
        AgentConfig(max_steps=5, subagent_max_steps=4),
        client,
        build_default_registry(),
        conv,
        ToolContext(workdir=tmp_path),
    )

    result = agent._spawn_subagent("审查目录")

    assert result == "子任务完成"
    # 独立上下文：子 agent 首轮消息是 system + 委托 prompt，不含主对话历史
    first = client.calls[0]
    assert first[0]["role"] == "system"
    assert first[1]["role"] == "user"
    assert first[1]["content"] == "审查目录"
    # 禁嵌套：子 agent 的工具集不含 task
    sub_tools = {t["function"]["name"] for t in client.tool_sets[0]}
    assert "task" not in sub_tools
    assert "list_dir" in sub_tools


def test_spawn_subagent_max_steps_returns_incomplete(tmp_path):
    client = ScriptedClient([
        resp(tool_calls=[tc("c1", "list_dir", '{"path": "."}')]),
        resp(tool_calls=[tc("c2", "list_dir", '{"path": "."}')]),
        resp(content="已完成一半，还差收尾验证", tool_calls=None, finish_reason="stop"),  # 收尾总结
    ])
    agent = make_agent(tmp_path, client, subagent_max_steps=2)
    result = agent._spawn_subagent("做不完的任务")
    assert "未完成" in result
    assert "已完成一半" in result  # 超步数前的进度总结被带回主 agent


def test_main_max_steps_summarizes_progress(tmp_path):
    client = ScriptedClient([
        resp(tool_calls=[tc("c1", "list_dir", '{"path": "."}')]),
        resp(tool_calls=[tc("c2", "list_dir", '{"path": "."}')]),
        resp(tool_calls=[tc("c3", "list_dir", '{"path": "."}')]),
        resp(content="进展：改了 x，尚未验证", tool_calls=None, finish_reason="stop"),  # 收尾总结
    ])
    agent = make_agent(tmp_path, client, max_steps=3)
    with pytest.raises(MaxStepsExceeded) as excinfo:
        agent.run("永远做不完")
    assert "进展" in str(excinfo.value)
    # 总结已作为 assistant 消息写入历史（供 /continue 续跑）
    assert agent.conversation.messages[-1].role == "assistant"
    assert "进展" in agent.conversation.messages[-1].content


def test_spawn_subagent_empty_result_signals(tmp_path):
    client = ScriptedClient([
        resp(content="", tool_calls=None, finish_reason="stop"),
    ])
    agent = make_agent(tmp_path, client)
    result = agent._spawn_subagent("做点啥")
    assert "未产出" in result


def test_spawn_subagent_inherits_permission(tmp_path, monkeypatch):
    executed: list[str] = []
    confirmed: list[str] = []

    def fake_run(command, **kwargs):
        executed.append(command)
        return NS(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("coding_agent.tools.bash.subprocess.run", fake_run)

    def _confirm(cmd):
        confirmed.append(cmd)
        return True

    client = ScriptedClient([
        resp(tool_calls=[tc("c1", "bash", '{"command": "rm -rf /tmp/x"}')]),
        resp(content="已清理", tool_calls=None, finish_reason="stop"),
    ])
    ctx = ToolContext(workdir=tmp_path)
    ctx.confirm = _confirm
    agent = Agent(
        AgentConfig(max_steps=5, subagent_max_steps=4),
        client,
        build_default_registry(),
        Conversation(system_prompt="sys"),
        ctx,
    )

    result = agent._spawn_subagent("清理临时文件")

    assert result == "已清理"
    assert confirmed == ["rm -rf /tmp/x"]  # 危险命令仍走确认（权限沿用）
    assert executed == ["rm -rf /tmp/x"]  # 确认通过后才真正执行


# --------------------------------------------------------------------------- #
# 主循环集成：委托 + 上下文隔离
# --------------------------------------------------------------------------- #


def test_main_delegates_and_isolates(tmp_path):
    client = ScriptedClient([
        resp(tool_calls=[tc("c1", "task", '{"prompt": "审查 foo.py"}')]),  # 主第 1 轮
        resp(tool_calls=[tc("c2", "list_dir", '{"path": "."}')]),  # 子第 1 轮
        resp(content="子任务完成", tool_calls=None, finish_reason="stop"),  # 子第 2 轮
        resp(content="整体完成", tool_calls=None, finish_reason="stop"),  # 主第 2 轮
    ])
    agent = make_agent(tmp_path, client)

    result = agent.run("审查项目并总结")

    assert result == "整体完成"
    # 主对话只有一条 tool 消息 = 子 agent 结论；中间过程（list_dir）不进入主上下文
    tool_msgs = [m for m in agent.conversation.messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].content == "子任务完成"
