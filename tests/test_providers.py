"""providers 模块测试：端点注册表。"""
from __future__ import annotations

import pytest

from coding_agent.errors import ConfigError
from coding_agent.llm.providers import PROVIDERS, resolve_provider


def test_resolve_deepseek():
    p = resolve_provider("deepseek")
    assert p.base_url == "https://api.deepseek.com"
    assert p.default_model == "deepseek-chat"


def test_resolve_is_case_insensitive():
    assert resolve_provider("DeepSeek").name == "deepseek"


def test_resolve_unknown_raises_configerror():
    with pytest.raises(ConfigError):
        resolve_provider("nonexistent")


def test_all_providers_have_valid_entries():
    for name, p in PROVIDERS.items():
        assert p.base_url.startswith("http"), name
        assert p.default_model, name
