"""OpenAI 兼容端点注册表。"""
from __future__ import annotations

from dataclasses import dataclass

from ..errors import ConfigError


@dataclass(frozen=True)
class Provider:
    """一个 OpenAI 兼容模型提供商。"""

    name: str
    base_url: str
    default_model: str


PROVIDERS: dict[str, Provider] = {
    "deepseek": Provider("deepseek", "https://api.deepseek.com", "deepseek-chat"),
    "qwen": Provider("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "glm": Provider("glm", "https://open.bigmodel.cn/api/paas/v4", "glm-4-plus"),
    "kimi": Provider("kimi", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "minimax": Provider("minimax", "https://api.minimaxi.com/v1", "abab6.5s-chat"),
}


def resolve_provider(name: str) -> Provider:
    """按名称解析提供商；未知名称抛 ConfigError。"""
    try:
        return PROVIDERS[name.strip().lower()]
    except KeyError as exc:
        raise ConfigError(
            f"未知 provider {name!r}，可选：{', '.join(PROVIDERS)}"
        ) from exc
