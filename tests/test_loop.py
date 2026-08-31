"""agent 主循环测试：用 mock LLM 离线驱动完整多轮闭环。"""
from __future__ import annotations

import pytest

from coding_agent.agent import Agent
from coding_agent.config import AgentConfig
from coding_agent.errors import MaxFailuresExceeded, MaxStepsExceeded
from coding_agent.llm.client import ChatResponse, ToolCall
from coding_agent.messages import Conversation
from coding_agent.tools import ToolContext, build_default_registry


class ScriptedClient:
    """按脚本依次返回 ChatResponse 的假客户端，记录每次调用。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools=None, on_text=None):
        self.calls.append(messages)
        resp = self.responses.pop(0)
        if on_text and resp.content:
            on_text(resp.content)
        return resp


def tc(id, name, arguments):
    return ToolCall(id=id, name=name, arguments=arguments)


def resp(content="", tool_calls=None, finish_reason="tool_calls"):
    return ChatResponse(content=content, tool_calls=tool_calls or [], finish_reason=finish_reason)


def make_agent(tmp_path, client, max_steps=10, max_failures=3):
    config = AgentConfig(max_steps=max_steps, max_failures=max_failures)
    return Agent(
        config,
        client,
        build_default_registry(),
        Conversation(system_prompt="sys"),
        ToolContext(workdir=tmp_path),
    )


def test_full_loop_read_edit_bash_deliver(tmp_path):
    (tmp_path / "foo.txt").write_text("hi\n")
    client = ScriptedClient([
        resp(tool_calls=[tc("c1", "read_file", '{"path": "foo.txt"}')]),
        resp(tool_calls=[tc("c2", "edit_file", '{"path": "foo.txt", "old_string": "hi", "new_string": "hello"}')]),
        resp(tool_calls=[tc("c3", "bash", '{"command": "cat foo.txt"}')]),
        resp(content="已完成", tool_calls=None, finish_reason="stop"),
    ])
    result = make_agent(tmp_path, client).run("把 hi 改成 hello 并验证")
    assert result == "已完成"
    assert (tmp_path / "foo.txt").read_text() == "hello\n"
    assert len(client.calls) == 4  # 四轮：读 → 改 → 跑 → 交付


def test_immediate_answer_terminates(tmp_path):
    client = ScriptedClient([resp(content="直接回答", tool_calls=None, finish_reason="stop")])
    result = make_agent(tmp_path, client).run("你好")
    assert result == "直接回答"
    assert len(client.calls) == 1


def test_max_steps_exceeded(tmp_path):
    # 模型一直要调用工具，永不给出最终回答
    client = ScriptedClient([
        resp(tool_calls=[tc("c1", "list_dir", '{"path": "."}')])
    ] * 3)
    agent = make_agent(tmp_path, client, max_steps=2)
    with pytest.raises(MaxStepsExceeded):
        agent.run("永远不会完成的任务")


def test_consecutive_failures_abort(tmp_path):
    client = ScriptedClient([
        resp(tool_calls=[tc("c1", "no_such_tool", "{}")]),
        resp(tool_calls=[tc("c2", "no_such_tool", "{}")]),
        resp(tool_calls=[tc("c3", "no_such_tool", "{}")]),
    ])
    agent = make_agent(tmp_path, client, max_failures=3)
    with pytest.raises(MaxFailuresExceeded):
        agent.run("触发失败")


def test_failure_then_recovery_resets_counter(tmp_path):
    (tmp_path / "f.txt").write_text("hi")
    client = ScriptedClient([
        # 第一次编辑失败（old_string 不匹配）
        resp(tool_calls=[tc("c1", "edit_file", '{"path": "f.txt", "old_string": "nope", "new_string": "x"}')]),
        # 第二次成功
        resp(tool_calls=[tc("c2", "edit_file", '{"path": "f.txt", "old_string": "hi", "new_string": "hello"}')]),
        resp(content="修好了", tool_calls=None, finish_reason="stop"),
    ])
    result = make_agent(tmp_path, client, max_failures=2).run("修复")
    assert result == "修好了"
    assert (tmp_path / "f.txt").read_text() == "hello"


def test_malformed_arguments_recovered(tmp_path):
    client = ScriptedClient([
        # 畸形 JSON → 解析失败，回传错误
        resp(tool_calls=[tc("c1", "bash", '{"command": 未闭合')]),
        # 模型修正后成功
        resp(tool_calls=[tc("c2", "bash", '{"command": "echo ok"}')]),
        resp(content="ok", tool_calls=None, finish_reason="stop"),
    ])
    result = make_agent(tmp_path, client).run("跑个命令")
    assert result == "ok"
