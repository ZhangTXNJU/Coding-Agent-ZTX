"""会话持久化：把 Conversation 序列化为 JSONL，存于 ~/.coding-agent/sessions/。

每条记录一行 JSON，类型区分 meta / system / summary / message，便于增量追加与续跑。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import AgentError
from .messages import Conversation, Message


def sessions_dir() -> Path:
    """会话目录（懒创建）。"""
    d = Path.home() / ".coding-agent" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class SessionMeta:
    """会话元数据（存于每条会话的首行）。"""

    id: str
    created_at: str
    provider: str = ""
    model: str = ""
    workdir: str = ""


def save_session(
    conversation: Conversation,
    *,
    provider: str = "",
    model: str = "",
    workdir: str = "",
    session_id: str | None = None,
) -> str:
    """保存会话，返回会话 ID（复用传入的 session_id 实现「续写同一会话」）。"""
    sid = session_id or uuid.uuid4().hex[:12]
    meta = SessionMeta(
        id=sid,
        created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        provider=provider,
        model=model,
        workdir=workdir,
    )
    lines = [json.dumps({"type": "meta", **asdict(meta)}, ensure_ascii=False)]
    if conversation.system_prompt:
        lines.append(
            json.dumps({"type": "system", "content": conversation.system_prompt}, ensure_ascii=False)
        )
    if conversation.summary:
        lines.append(
            json.dumps({"type": "summary", "content": conversation.summary}, ensure_ascii=False)
        )
    for m in conversation.messages:
        lines.append(
            json.dumps(
                {
                    "type": "message",
                    "role": m.role,
                    "content": m.content,
                    "tool_calls": m.tool_calls,
                    "tool_call_id": m.tool_call_id,
                    "name": m.name,
                },
                ensure_ascii=False,
            )
        )
    path = sessions_dir() / f"{sid}.jsonl"
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        raise AgentError(f"会话写入失败：{exc}") from exc
    return sid


def load_session(session_id: str) -> Conversation:
    """从磁盘恢复会话；会话不存在或损坏时抛 AgentError。"""
    path = sessions_dir() / f"{session_id}.jsonl"
    if not path.exists():
        raise AgentError(f"会话不存在：{session_id}")
    conv = Conversation()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentError(f"会话读取失败：{exc}") from exc

    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AgentError(f"会话文件损坏：{path.name}") from exc
        kind = obj.get("type")
        if kind == "system":
            conv.system_prompt = obj.get("content", "")
        elif kind == "summary":
            conv.summary = obj.get("content", "")
        elif kind == "message":
            conv.messages.append(
                Message(
                    role=obj["role"],
                    content=obj.get("content", ""),
                    tool_calls=obj.get("tool_calls", []),
                    tool_call_id=obj.get("tool_call_id"),
                    name=obj.get("name"),
                )
            )
    return conv


def list_sessions() -> list[SessionMeta]:
    """列出所有会话元数据，按创建时间排序。"""
    out: list[SessionMeta] = []
    for p in sorted(sessions_dir().glob("*.jsonl")):
        try:
            first = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
        except (OSError, json.JSONDecodeError, IndexError):
            continue
        if first.get("type") != "meta":
            continue
        out.append(
            SessionMeta(
                id=first.get("id", p.stem),
                created_at=first.get("created_at", ""),
                provider=first.get("provider", ""),
                model=first.get("model", ""),
                workdir=first.get("workdir", ""),
            )
        )
    out.sort(key=lambda s: s.created_at)
    return out


def latest_session_id() -> str | None:
    """最近一次会话的 ID；无会话返回 None。"""
    sessions = list_sessions()
    return sessions[-1].id if sessions else None
