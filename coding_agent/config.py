"""配置加载：命令行参数 > 环境变量 > .env > 内置默认。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .llm.providers import resolve_provider


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int_env(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class AgentConfig:
    """agent 运行配置。"""

    provider: str = "deepseek"
    model: str = ""  # 空则用 provider 默认模型
    base_url: str = ""  # 空则用 provider 默认端点
    api_key: str = ""  # 仅从环境变量读取，绝不落盘
    max_steps: int = 30
    max_failures: int = 3
    command_timeout: int = 120
    max_tokens: int = 48_000  # 上下文预算（估算 token），默认给 DeepSeek 64K 留出余量
    max_tool_result_chars: int = 20_000  # 单次工具结果写入上下文前的截断上限
    subagent_max_steps: int = 15  # 子 agent 的最大循环步数（比主循环小，防失控）
    auto_approve: bool = False
    workdir: Path = field(default_factory=Path.cwd)

    @property
    def resolved_model(self) -> str:
        return self.model or resolve_provider(self.provider).default_model

    @property
    def resolved_base_url(self) -> str:
        return self.base_url or resolve_provider(self.provider).base_url

    def __repr__(self) -> str:  # 不泄露 api_key
        return (
            f"AgentConfig(provider={self.provider!r}, model={self.resolved_model!r}, "
            f"base_url={self.resolved_base_url!r}, api_key=<set:{bool(self.api_key)}>, "
            f"max_steps={self.max_steps}, max_failures={self.max_failures}, "
            f"command_timeout={self.command_timeout}, max_tokens={self.max_tokens}, "
            f"max_tool_result_chars={self.max_tool_result_chars}, "
            f"subagent_max_steps={self.subagent_max_steps}, auto_approve={self.auto_approve})"
        )


def load_config(**overrides) -> AgentConfig:
    """加载配置。overrides 来自命令行参数（仅覆盖显式传入、非 None 的项）。"""
    load_dotenv()  # 读取 .env，不覆盖已存在的环境变量

    data: dict = {
        "provider": _env("CODING_AGENT_PROVIDER", "deepseek"),
        "model": _env("CODING_AGENT_MODEL"),
        "base_url": _env("CODING_AGENT_BASE_URL"),
        "api_key": _env("CODING_AGENT_API_KEY"),
        "max_steps": _int_env("CODING_AGENT_MAX_STEPS", 30),
        "max_failures": _int_env("CODING_AGENT_MAX_FAILURES", 3),
        "command_timeout": _int_env("CODING_AGENT_COMMAND_TIMEOUT", 120),
        "max_tokens": _int_env("CODING_AGENT_MAX_TOKENS", 48_000),
        "max_tool_result_chars": _int_env("CODING_AGENT_MAX_TOOL_RESULT_CHARS", 20_000),
        "subagent_max_steps": _int_env("CODING_AGENT_SUBAGENT_MAX_STEPS", 15),
        "auto_approve": _env("CODING_AGENT_AUTO_APPROVE").lower() in ("1", "true", "yes"),
    }
    for key, value in overrides.items():
        if value is not None:
            data[key] = value
    return AgentConfig(**data)
