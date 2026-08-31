"""errors 模块测试：错误层级 + 指数退避重试。"""
from __future__ import annotations

import pytest

from coding_agent import errors
from coding_agent.errors import (
    AgentError,
    ConfigError,
    LLMError,
    MaxFailuresExceeded,
    MaxStepsExceeded,
    ParsingError,
    ToolError,
    with_retry,
)


def test_error_hierarchy():
    for cls in (
        ConfigError,
        LLMError,
        ToolError,
        ParsingError,
        MaxStepsExceeded,
        MaxFailuresExceeded,
    ):
        assert issubclass(cls, AgentError)


def test_with_retry_succeeds_first_try():
    calls: list[int] = []

    @with_retry(retries=3)
    def f():
        calls.append(1)
        return "ok"

    assert f() == "ok"
    assert len(calls) == 1


def test_with_retry_retries_then_succeeds():
    calls: list[int] = []

    @with_retry(retries=3, backoff=0)
    def f():
        calls.append(1)
        if len(calls) < 3:
            raise LLMError("boom")
        return "ok"

    assert f() == "ok"
    assert len(calls) == 3


def test_with_retry_non_retryable_not_retried():
    calls: list[int] = []

    @with_retry(retries=3, retryable=(LLMError,), backoff=0)
    def f():
        calls.append(1)
        raise ValueError("不可重试")

    with pytest.raises(ValueError):
        f()
    assert len(calls) == 1


def test_with_retry_exhausts_retries():
    calls: list[int] = []

    @with_retry(retries=2, backoff=0)
    def f():
        calls.append(1)
        raise LLMError("一直失败")

    with pytest.raises(LLMError):
        f()
    assert len(calls) == 3  # 1 次初始 + 2 次重试


def test_with_retry_exponential_backoff(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(errors.time, "sleep", lambda s: sleeps.append(s))

    @with_retry(retries=3, backoff=1.0, max_backoff=8.0)
    def f():
        raise LLMError("boom")

    with pytest.raises(LLMError):
        f()
    assert sleeps == [1.0, 2.0, 4.0]
