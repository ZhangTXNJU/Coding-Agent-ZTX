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


def test_resolve_skill_invocation():
    from coding_agent.cli import _resolve_skill_invocation
    from coding_agent.skills import Skill, SkillRegistry

    reg = SkillRegistry()
    reg.register(Skill("code-review", "审查代码质量", "指引", "builtin"))

    # 非斜杠 / 内置命令 / 未注册的 skill 名 → 不当作 skill 调用
    assert _resolve_skill_invocation("普通任务", reg) is None
    assert _resolve_skill_invocation("/help", reg) is None
    assert _resolve_skill_invocation("/nope", reg) is None

    # 纯 skill 名
    skill, rest = _resolve_skill_invocation("/code-review", reg)
    assert skill.name == "code-review" and rest == ""

    # skill 名 + 附加自然语言提示
    skill, rest = _resolve_skill_invocation("/code-review 检查 src/ 目录", reg)
    assert skill.name == "code-review" and rest == "检查 src/ 目录"
