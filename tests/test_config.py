"""config 模块测试：三级配置加载 + 凭据安全。"""
from __future__ import annotations

from coding_agent.config import load_config


def test_defaults():
    c = load_config()
    assert c.provider == "deepseek"
    assert c.api_key == ""
    assert c.max_steps == 30
    assert c.max_failures == 3
    assert c.command_timeout == 120
    assert c.max_tokens == 48_000
    assert c.max_tool_result_chars == 20_000
    assert c.resolved_model == "deepseek-chat"
    assert c.resolved_base_url == "https://api.deepseek.com"


def test_env_override(monkeypatch):
    monkeypatch.setenv("CODING_AGENT_MODEL", "deepseek-reasoner")
    monkeypatch.setenv("CODING_AGENT_API_KEY", "sk-test")
    c = load_config()
    assert c.model == "deepseek-reasoner"
    assert c.api_key == "sk-test"


def test_cli_override_wins_over_env(monkeypatch):
    monkeypatch.setenv("CODING_AGENT_MODEL", "from-env")
    c = load_config(model="from-cli", max_steps=7)
    assert c.model == "from-cli"
    assert c.max_steps == 7


def test_workdir_defaults_to_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    c = load_config()
    assert c.workdir == tmp_path


def test_provider_switch_resolves_defaults():
    c = load_config(provider="qwen")
    assert c.resolved_model == "qwen-plus"
    assert "dashscope" in c.resolved_base_url


def test_repr_hides_api_key(monkeypatch):
    monkeypatch.setenv("CODING_AGENT_API_KEY", "sk-secret-123")
    c = load_config()
    r = repr(c)
    assert "sk-secret-123" not in r
    assert "api_key=<set:True>" in r


def test_invalid_int_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CODING_AGENT_MAX_STEPS", "not-a-number")
    assert load_config().max_steps == 30


def test_auto_approve_parsing(monkeypatch):
    for value in ("true", "1", "yes"):
        monkeypatch.setenv("CODING_AGENT_AUTO_APPROVE", value)
        assert load_config().auto_approve is True
    monkeypatch.setenv("CODING_AGENT_AUTO_APPROVE", "no")
    assert load_config().auto_approve is False
