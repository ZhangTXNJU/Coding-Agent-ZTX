"""OpenAI 兼容流式客户端（薄封装，不含任何编排逻辑）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

from openai import OpenAI

from ..config import AgentConfig
from ..errors import LLMError, with_retry


@dataclass
class ToolCall:
    """模型发起的一次工具调用。arguments 仍为 JSON 字符串，后续由 parsing 解析。"""

    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class ChatResponse:
    """一次模型调用的完整结果。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""


class LLMClient:
    """OpenAI 兼容 chat/completions 客户端，支持流式输出与工具调用累积。"""

    def __init__(self, config: AgentConfig):
        self._model = config.resolved_model
        self._client = OpenAI(api_key=config.api_key, base_url=config.resolved_base_url)

    @with_retry(retries=3, retryable=(LLMError,))
    def chat(
        self,
        messages: list[Mapping],
        tools: list[Mapping] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> ChatResponse:
        """发送一轮对话。

        messages：OpenAI 格式消息列表；tools：OpenAI 格式工具定义列表；
        on_text：流式文本回调（逐 token 触发）。
        """
        kwargs: dict = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        try:
            stream = self._client.chat.completions.create(stream=True, **kwargs)
        except Exception as exc:  # openai SDK 会抛出多种异常
            raise LLMError(f"调用模型失败: {exc}") from exc
        return self._collect(stream, on_text)

    def _collect(self, stream, on_text: Callable[[str], None] | None) -> ChatResponse:
        """从流式 chunk 累积 content 与 tool_calls（按 index 合并分片）。"""
        content_parts: list[str] = []
        tool_calls: dict[int, ToolCall] = {}
        finish_reason = ""
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta is None:
                    continue
                if delta.content:
                    content_parts.append(delta.content)
                    if on_text is not None:
                        on_text(delta.content)
                for tc in delta.tool_calls or []:
                    slot = tool_calls.setdefault(tc.index, ToolCall())
                    if tc.id:
                        slot.id = tc.id
                    fn = tc.function
                    if fn is not None:
                        if fn.name:
                            slot.name = fn.name
                        if fn.arguments:
                            slot.arguments += fn.arguments
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
        except Exception as exc:
            raise LLMError(f"流式读取失败: {exc}") from exc
        return ChatResponse(
            content="".join(content_parts),
            tool_calls=[tool_calls[i] for i in sorted(tool_calls)],
            finish_reason=finish_reason,
        )
