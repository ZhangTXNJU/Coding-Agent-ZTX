"""messages 模块测试：消息模型、序列化、token 估算、压缩。"""
from __future__ import annotations

from coding_agent.messages import Conversation, Message, estimate_tokens, messages_to_text, truncate_text


def test_message_to_openai_by_role():
    assert Message("user", "hi").to_openai() == {"role": "user", "content": "hi"}
    tc = [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]
    m = Message("assistant", "", tool_calls=tc)
    assert m.to_openai()["tool_calls"] == tc
    t = Message("tool", "ok", tool_call_id="c1", name="read_file")
    assert t.to_openai() == {"role": "tool", "content": "ok", "tool_call_id": "c1", "name": "read_file"}


def test_conversation_serialization():
    c = Conversation(system_prompt="sys")
    c.add_user("做任务")
    c.add_assistant("", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}])
    c.add_tool("c1", "exit_code: 0", name="bash")
    msgs = c.to_openai()
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "做任务"}
    assert msgs[-1]["role"] == "tool"


def test_estimate_tokens_counts_cjk():
    # 中文字符按 1 token，英文按 4 字符 1 token
    assert estimate_tokens("你好") == 2
    assert estimate_tokens("") == 0


def test_conversation_estimate_tokens_grows():
    c = Conversation(system_prompt="sys")
    assert c.estimate_tokens() > 0
    c.add_user("hello world " * 100)
    assert c.estimate_tokens() > 100


def test_trim_tool_results():
    c = Conversation()
    c.add_tool("c1", "x" * 10000, name="read_file")
    trimmed = c.trim_tool_results(max_chars=1000)
    assert trimmed == 1
    assert "已省略" in c.messages[0].content
    assert len(c.messages[0].content) < 10000


def test_compact_keeps_recent():
    c = Conversation()
    for i in range(10):
        c.add_user(f"msg {i}")
    c.compact(lambda old: f"摘要了 {len(old)} 条", keep_recent=4)
    assert len(c.messages) == 4
    assert "摘要了 6 条" in c.summary
    assert c.messages[-1].content == "msg 9"


def test_compact_noop_when_short():
    c = Conversation()
    c.add_user("only one")
    c.compact(lambda old: "x", keep_recent=4)
    assert c.summary == ""
    assert len(c.messages) == 1


def test_messages_to_text():
    msgs = [Message("user", "hello"), Message("tool", "x" * 1000, name="grep")]
    text = messages_to_text(msgs)
    assert "[user] hello" in text
    assert "[tool:grep]" in text
    assert len(text) < 600  # 工具结果被截断


def test_truncate_text_keeps_head_tail():
    text = "abcdefghij" * 100  # 1000 字符
    out = truncate_text(text, max_chars=100)
    assert len(out) < 1000
    assert "已省略" in out
    assert out.startswith("abcdefghij")
    assert out.endswith("abcdefghij")


def test_truncate_text_noop_when_short():
    text = "hello"
    assert truncate_text(text, max_chars=100) == text


def test_compact_tail_never_starts_with_tool():
    # 构造：尾部若按朴素 keep_recent 切分会落在 tool 消息上（其 assistant 已被折叠），
    # 边界安全逻辑应推进切点，使尾部以非 tool 消息开头。
    c = Conversation()
    c.add_user("任务")
    for i in range(6):
        c.add_assistant("", tool_calls=[{"id": f"c{i}", "type": "function", "function": {"name": "bash", "arguments": "{}"}}])
        c.add_tool(f"c{i}", f"result {i}", name="bash")
    c.compact(messages_to_text, keep_recent=6)
    # 折叠后首条消息不应是孤立的 tool 消息
    assert c.messages[0].role in ("user", "assistant")
    assert c.summary != ""


def test_compact_accumulates_prior_summary():
    def _join(messages):
        return " | ".join(m.content for m in messages)

    c = Conversation()
    for i in range(10):
        c.add_user(f"msg {i}")
    c.compact(_join, keep_recent=4)
    assert "msg 0" in c.summary and "msg 5" in c.summary
    c.add_user("继续")
    c.add_user("继续2")
    c.add_user("继续3")
    c.compact(_join, keep_recent=2)
    # 上一轮摘要应作为输入并入第二轮，而不是被丢弃
    assert "msg 0" in c.summary
