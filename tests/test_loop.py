"""agent 主循环测试：用 mock LLM 离线驱动完整多轮闭环。"""
from __future__ import annotations

import pytest

from coding_agent.agent import Agent
from coding_agent.config import AgentConfig
from coding_agent.errors import LLMError, MaxFailuresExceeded, MaxStepsExceeded
from coding_agent.llm.client import ChatResponse, ToolCall
from coding_agent.messages import Conversation, Message, messages_to_text
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


def test_tool_result_truncated_in_context(tmp_path):
    # 工具返回超长结果时，写入上下文前应被截断
    (tmp_path / "big.txt").write_text("x" * 25_000)
    client = ScriptedClient([
        resp(tool_calls=[tc("c1", "read_file", '{"path": "big.txt"}')]),
        resp(content="已读", tool_calls=None, finish_reason="stop"),
    ])
    agent = make_agent(tmp_path, client)
    agent.run("读大文件")
    tool_msg = next(m for m in agent.conversation.messages if m.role == "tool")
    assert "已省略" in tool_msg.content
    assert len(tool_msg.content) < 25_000


def test_compaction_triggers_when_over_budget(tmp_path):
    # 用小预算强制触发压缩：大量历史应被折叠成摘要
    config = AgentConfig(max_steps=3, max_failures=3, max_tokens=300)
    client = ScriptedClient([
        resp(tool_calls=[tc("c1", "list_dir", '{"path": "."}')]),
        resp(content="完成", tool_calls=None, finish_reason="stop"),
    ])
    conv = Conversation(system_prompt="sys")
    for i in range(40):
        conv.add_user(f"历史消息 {i} " + "x" * 80)
    agent = Agent(config, client, build_default_registry(), conv, ToolContext(workdir=tmp_path))
    agent.run("继续")
    assert conv.summary != ""
    assert len(conv.messages) < 40


def test_compaction_uses_model_summary(tmp_path):
    # 压缩触发时应优先采用 LLM 语义摘要，而非确定性 flatten
    config = AgentConfig(max_steps=3, max_failures=3, max_tokens=300)
    client = ScriptedClient([
        resp(content="## 目标\n早期历史摘要", tool_calls=None, finish_reason="stop"),  # 压缩用的摘要
        resp(content="完成", tool_calls=None, finish_reason="stop"),  # 主循环最终回答
    ])
    conv = Conversation(system_prompt="sys")
    for i in range(40):
        conv.add_user(f"历史消息 {i} " + "x" * 80)
    agent = Agent(config, client, build_default_registry(), conv, ToolContext(workdir=tmp_path))
    agent.run("继续")
    assert "早期历史摘要" in conv.summary
    assert len(conv.messages) < 40


def test_llm_summarize_returns_model_summary(tmp_path):
    client = ScriptedClient([
        resp(content="## 目标\n完成重构", tool_calls=None, finish_reason="stop"),
    ])
    agent = make_agent(tmp_path, client)
    msgs = [Message("user", "把 a 改成 b"), Message("tool", "很长的输出", name="bash")]
    assert agent._llm_summarize(msgs) == "## 目标\n完成重构"


def test_llm_summarize_falls_back_on_llm_error(tmp_path):
    class FailingClient:
        def chat(self, messages, tools=None, on_text=None):
            raise LLMError("模型不可用")

    agent = make_agent(tmp_path, FailingClient())
    msgs = [Message("user", "hello"), Message("tool", "out", name="bash")]
    assert agent._llm_summarize(msgs) == messages_to_text(msgs)


def test_llm_summarize_falls_back_on_empty(tmp_path):
    # 模型返回空内容也应回退确定性 flatten
    client = ScriptedClient([resp(content="", tool_calls=None, finish_reason="stop")])
    agent = make_agent(tmp_path, client)
    msgs = [Message("user", "hello")]
    assert agent._llm_summarize(msgs) == messages_to_text(msgs)


def test_run_with_skill_injects_and_restores_system_prompt(tmp_path):
    from coding_agent.skills import Skill

    client = ScriptedClient([resp(content="完成", tool_calls=None, finish_reason="stop")])
    agent = make_agent(tmp_path, client)
    original = agent.conversation.system_prompt

    skill = Skill("code-review", "审查代码质量", "第一步：审查代码。", "builtin")
    result = agent.run("请审查", skill=skill)

    assert result == "完成"
    # 第一次调用的 system 消息应包含注入的 skill 指引
    assert "第一步：审查代码。" in client.calls[0][0]["content"]
    # run 结束后系统提示恢复，不污染后续对话
    assert agent.conversation.system_prompt == original


def test_todos_injected_into_system_each_turn(tmp_path):
    client = ScriptedClient([resp(content="完成", tool_calls=None, finish_reason="stop")])
    agent = make_agent(tmp_path, client)
    agent.conversation.todos[:] = [{"id": 1, "content": "写代码", "status": "in_progress"}]
    agent.run("继续")
    system_msg = client.calls[0][0]
    assert system_msg["role"] == "system"
    assert "当前任务清单" in system_msg["content"]
    assert "写代码" in system_msg["content"]


def test_todos_not_lost_by_compaction(tmp_path):
    agent = make_agent(tmp_path, ScriptedClient([]))
    agent.conversation.todos[:] = [{"id": 1, "content": "写代码", "status": "in_progress"}]
    for i in range(40):
        agent.conversation.add_user(f"历史 {i} " + "x" * 80)
    agent.conversation.compact(lambda msgs: "早期历史摘要")  # 折叠旧消息
    assert len(agent.conversation.messages) < 40  # 确实发生压缩
    # 压缩后 todo 仍被注入（独立于 messages 历史，不随折叠丢失）
    assert "写代码" in agent._messages_with_todos()[0]["content"]


def test_replace_conversation_syncs_todos(tmp_path):
    agent = make_agent(tmp_path, ScriptedClient([]))
    new_conv = Conversation(system_prompt="new")
    new_conv.todos[:] = [{"id": 1, "content": "跑测试", "status": "pending"}]
    agent.replace_conversation(new_conv)
    assert agent.system_prompt == "new"
    assert agent.ctx.todos == new_conv.todos
    assert agent.conversation is new_conv
