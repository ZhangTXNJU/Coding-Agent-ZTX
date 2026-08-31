"""共享 fixture：环境隔离，保证测试确定性。"""
from __future__ import annotations

import pytest

import coding_agent.config as config_mod

_ENV_VARS = [
    "CODING_AGENT_PROVIDER",
    "CODING_AGENT_MODEL",
    "CODING_AGENT_BASE_URL",
    "CODING_AGENT_API_KEY",
    "CODING_AGENT_MAX_STEPS",
    "CODING_AGENT_MAX_FAILURES",
    "CODING_AGENT_COMMAND_TIMEOUT",
    "CODING_AGENT_AUTO_APPROVE",
]


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """禁用 .env 读取并清空相关环境变量，避免本机配置污染测试。"""
    monkeypatch.setattr(config_mod, "load_dotenv", lambda *a, **k: True)
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _isolate_sessions(monkeypatch, tmp_path):
    """把会话目录重定向到临时目录，避免测试写入 ~/.coding-agent。"""
    import coding_agent.session as session_mod

    d = tmp_path / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(session_mod, "sessions_dir", lambda: d)
