"""会话持久化测试：保存/加载往返、缺失报错、最近会话。"""
from __future__ import annotations

import pytest

from coding_agent.errors import AgentError
from coding_agent.messages import Conversation
from coding_agent.session import latest_session_id, load_session, save_session


@pytest.fixture
def _tmp_sessions(monkeypatch, tmp_path):
    monkeypatch.setattr("coding_agent.session.sessions_dir", lambda: tmp_path)
    return tmp_path


def test_roundtrip(_tmp_sessions):
    conv = Conversation(system_prompt="sys")
    conv.add_user("你好")
    conv.add_assistant(
        "我来读文件",
        tool_calls=[
            {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"a"}'}}
        ],
    )
    conv.add_tool("c1", "文件内容", name="read_file")

    sid = save_session(conv, provider="deepseek", model="deepseek-chat", workdir="/tmp")
    loaded = load_session(sid)

    assert loaded.system_prompt == "sys"
    assert [m.role for m in loaded.messages] == ["user", "assistant", "tool"]
    assert loaded.messages[1].tool_calls[0]["function"]["name"] == "read_file"
    assert loaded.messages[2].name == "read_file"
    assert loaded.messages[2].tool_call_id == "c1"


def test_reuse_session_id_appends(_tmp_sessions):
    save_session(Conversation(system_prompt="s"), session_id="abc123")
    conv = Conversation(system_prompt="s")
    conv.add_user("第二轮")
    sid = save_session(conv, session_id="abc123")
    assert sid == "abc123"
    assert len(load_session("abc123").messages) == 1


def test_missing_session_raises(_tmp_sessions):
    with pytest.raises(AgentError):
        load_session("nonexistent")


def test_latest_session(_tmp_sessions):
    assert latest_session_id() is None
    save_session(Conversation())
    assert latest_session_id() is not None
