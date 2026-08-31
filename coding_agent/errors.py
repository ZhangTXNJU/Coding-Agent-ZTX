"""错误类型与重试策略。

本模块无包内依赖，避免循环导入。
"""
from __future__ import annotations

import functools
import time
from typing import Callable, TypeVar

T = TypeVar("T")


class AgentError(Exception):
    """agent 运行期错误基类。"""


class ConfigError(AgentError):
    """配置错误（缺 key、未知 provider、非法参数等）。"""


class LLMError(AgentError):
    """模型 API 调用错误（网络/限流/5xx 等）。"""


class ToolError(AgentError):
    """工具本地执行错误。"""


class ParsingError(AgentError):
    """模型输出解析错误。"""


class MaxStepsExceeded(AgentError):
    """达到最大循环步数。"""


class MaxFailuresExceeded(AgentError):
    """连续失败次数超阈值。"""


def with_retry(
    retries: int = 3,
    backoff: float = 1.0,
    max_backoff: float = 8.0,
    retryable: tuple[type[Exception], ...] = (LLMError,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """指数退避重试装饰器，仅对 retryable 异常重试。"""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            delay = backoff
            last_exc: Exception | None = None
            for attempt in range(retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable as exc:  # noqa: PERF203
                    last_exc = exc
                    if attempt == retries:
                        break
                    time.sleep(delay)
                    delay = min(delay * 2, max_backoff)
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
