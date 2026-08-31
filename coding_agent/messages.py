"""对话历史与上下文管理：消息模型 + token 估算 + 三级压缩。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Iterable


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：CJK 字符约 1 token，其余约 4 字符 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    other = len(text) - cjk
    return cjk + (other + 3) // 4  # 向上取整，短文本至少 1 token


@dataclass
class Message:
    """单条消息。tool_calls 使用 OpenAI 线上格式（list[dict]）。"""

    role: str  # system / user / assistant / tool
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai(self) -> dict:
        msg: dict = {"role": self.role, "content": self.content}
        if self.role == "assistant" and self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.role == "tool":
            msg["tool_call_id"] = self.tool_call_id
            if self.name:
                msg["name"] = self.name
        return msg


@dataclass
class Conversation:
    """一条完整对话的容器，管理上下文生命周期。"""

    system_prompt: str = ""
    messages: list[Message] = field(default_factory=list)
    max_tokens: int = 96_000
    summary: str = ""

    # -- 追加 --------------------------------------------------------------- #

    def add_user(self, content: str) -> None:
        self.messages.append(Message("user", content))

    def add_assistant(self, content: str, tool_calls: list[dict] | None = None) -> None:
        self.messages.append(Message("assistant", content, tool_calls or []))

    def add_tool(self, tool_call_id: str, content: str, name: str | None = None) -> None:
        self.messages.append(Message("tool", content, tool_call_id=tool_call_id, name=name))

    # -- 序列化 ------------------------------------------------------------- #

    def to_openai(self) -> list[dict]:
        result: list[dict] = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        if self.summary:
            result.append({"role": "user", "content": f"[历史摘要]\n{self.summary}"})
        result.extend(m.to_openai() for m in self.messages)
        return result

    # -- token 预算 ---------------------------------------------------------- #

    def estimate_tokens(self) -> int:
        total = estimate_tokens(self.system_prompt) + estimate_tokens(self.summary)
        for m in self.messages:
            total += estimate_tokens(m.content)
            for tc in m.tool_calls:
                total += estimate_tokens(json.dumps(tc, ensure_ascii=False))
        return total

    def needs_compaction(self) -> bool:
        return self.estimate_tokens() > self.max_tokens

    # -- 三级压缩 ------------------------------------------------------------ #

    def trim_tool_results(self, max_chars: int = 4000) -> int:
        """一级：裁剪超长工具结果（保留首尾 + 省略标记）。返回被裁剪条数。"""
        trimmed = 0
        for m in self.messages:
            if m.role == "tool" and len(m.content) > max_chars:
                half = max_chars // 2
                m.content = (
                    m.content[:half]
                    + f"\n…[中间 {len(m.content) - max_chars} 字符已省略]…\n"
                    + m.content[-half:]
                )
                trimmed += 1
        return trimmed

    def compact(self, summarizer: Callable[[list[Message]], str], keep_recent: int = 6) -> str:
        """二/三级：把较早消息折叠成摘要，仅保留最近 keep_recent 条。返回摘要文本。"""
        if len(self.messages) <= keep_recent:
            return ""
        old = self.messages[:-keep_recent]
        self.summary = summarizer(old)
        self.messages = self.messages[-keep_recent:]
        return self.summary


def messages_to_text(messages: Iterable[Message]) -> str:
    """把一组消息折叠成纯文本（供摘要器使用）。"""
    lines = []
    for m in messages:
        if m.role == "tool":
            lines.append(f"[tool:{m.name}] {m.content[:500]}")
        else:
            lines.append(f"[{m.role}] {m.content}")
    return "\n".join(lines)
