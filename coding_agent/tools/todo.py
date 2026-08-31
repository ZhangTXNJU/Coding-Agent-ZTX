"""任务清单工具：todo_write（规划记忆）。"""
from __future__ import annotations

from .registry import Tool, ToolContext

_MARK = {"pending": " ", "in_progress": "→", "completed": "x"}


def todo_write(args: dict, ctx: ToolContext) -> str:
    todos = args["todos"]
    ctx.todos[:] = todos  # 替换为最新清单，状态随会话持久
    if not todos:
        return "任务清单为空"
    lines = []
    for t in todos:
        status = t.get("status", "pending")
        mark = _MARK.get(status, " ")
        lines.append(f"- [{mark}] #{t.get('id')} {t.get('content', '')}")
    return "\n".join(lines)


TODO_WRITE = Tool(
    name="todo_write",
    description="更新任务清单：列出计划、标记进行中/完成。",
    parameters={
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "content": {"type": "string"},
                        "status": {"enum": ["pending", "in_progress", "completed"]},
                    },
                    "required": ["id", "content", "status"],
                },
            }
        },
        "required": ["todos"],
    },
    handler=todo_write,
)
