"""LLM client 测试：流式累积 + 重试（全部离线，不调用真实 API）。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from coding_agent.errors import LLMError
from coding_agent.llm.client import LLMClient


def _chunk(delta_content=None, tool_deltas=None, finish=None):
    delta = NS(content=delta_content, tool_calls=tool_deltas or [])
    return NS(choices=[NS(delta=delta, finish_reason=finish)])


def _td(index, id=None, name=None, args=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=args))


def _client_with_stream(stream):
    """构造一个 LLMClient，其 create() 返回给定流。"""
    client = object.__new__(LLMClient)
    client._model = "deepseek-chat"
    client._client = NS(chat=NS(completions=NS(create=lambda **kw: iter(stream))))
    return client


def test_collect_text_only():
    stream = [_chunk("hello "), _chunk("world", finish="stop")]
    resp = LLMClient._collect(object.__new__(LLMClient), iter(stream), None)
    assert resp.content == "hello world"
    assert resp.finish_reason == "stop"
    assert resp.tool_calls == []


def test_collect_accumulates_fragmented_tool_calls():
    # 模拟 OpenAI 把 tool_calls 按 index 分片流式下发
    stream = [
        _chunk(tool_deltas=[_td(0, id="c1", name="read_file", args='{"pa')]),
        _chunk(tool_deltas=[_td(0, args='th":"a.py"}')]),
        _chunk(tool_deltas=[_td(1, id="c2", name="bash", args='{"command":"ls"}')]),
        _chunk(finish="tool_calls"),
    ]
    resp = LLMClient._collect(object.__new__(LLMClient), iter(stream), None)
    assert resp.finish_reason == "tool_calls"
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0].name == "read_file"
    assert resp.tool_calls[0].arguments == '{"path":"a.py"}'  # 分片被正确合并
    assert resp.tool_calls[1].name == "bash"
    assert resp.tool_calls[1].arguments == '{"command":"ls"}'


def test_collect_on_text_callback():
    seen: list[str] = []
    stream = [_chunk("ab"), _chunk("cd")]
    LLMClient._collect(object.__new__(LLMClient), iter(stream), seen.append)
    assert seen == ["ab", "cd"]


def test_chat_returns_response():
    client = _client_with_stream([_chunk("hi", finish="stop")])
    resp = client.chat([{"role": "user", "content": "x"}])
    assert resp.content == "hi"


def test_chat_raises_llmerror_on_create_failure(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)  # 避免真实退避等待

    def create(**kw):
        raise RuntimeError("network down")

    client = object.__new__(LLMClient)
    client._model = "m"
    client._client = NS(chat=NS(completions=NS(create=create)))
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "x"}])


def test_chat_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls: list[int] = []

    def create(**kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return iter([_chunk("ok", finish="stop")])

    client = object.__new__(LLMClient)
    client._model = "m"
    client._client = NS(chat=NS(completions=NS(create=create)))
    resp = client.chat([{"role": "user", "content": "x"}])
    assert resp.content == "ok"
    assert len(calls) == 2
