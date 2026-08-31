"""CLI 入口测试。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from coding_agent.cli import main


def test_help_exits_zero():
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0


def test_no_key_returns_error(capsys):
    assert main([]) == 1
    assert "API key" in capsys.readouterr().err


def test_no_task_with_key_prompts_usage(monkeypatch, capsys):
    monkeypatch.setenv("CODING_AGENT_API_KEY", "sk-test")
    assert main([]) == 0
    assert "python -m coding_agent" in capsys.readouterr().out


def test_run_with_fake_client(monkeypatch, capsys):
    from coding_agent.llm.client import ChatResponse

    monkeypatch.setenv("CODING_AGENT_API_KEY", "sk-test")

    class FakeClient:
        def __init__(self, config):
            pass

        def chat(self, messages, tools=None, on_text=None):
            on_text("fake response")
            return ChatResponse(content="fake response", finish_reason="stop")

    monkeypatch.setattr("coding_agent.llm.client.LLMClient", FakeClient)
    assert main(["hello"]) == 0
    assert "fake response" in capsys.readouterr().out
