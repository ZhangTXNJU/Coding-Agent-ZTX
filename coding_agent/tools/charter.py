"""charter 工具：读取 / 追加项目宪章（工作目录 Coding-Agent.md）。

宪章把「无论如何不能动的内容 / 必须始终遵守的规范」等关键约束固化到文件里，
独立于对话历史、不会被上下文压缩遗忘（启动时还会注入 system prompt）。

与 ask_user / skill 等工具同构：纯函数 handler + Tool 定义，注册进默认注册表即可。
"""
from __future__ import annotations

from ..charter import CHARTER_FILENAME, charter_path
from ..errors import ToolError
from .registry import Tool, ToolContext

_ADD_TITLE = "\n\n## 项目宪章（追加）\n"


def read_charter(args: dict, ctx: ToolContext) -> str:
    """读宪章：返回 Coding-Agent.md 的当前内容；不存在则给出提示。"""
    p = charter_path(ctx.workdir)
    if not p.is_file():
        return f"当前工作目录没有宪章（{CHARTER_FILENAME}）。如需固化全局规则，可用 charter 工具 action=add 添加。"
    text = p.read_text(encoding="utf-8")
    return f"{CHARTER_FILENAME} 内容（{len(text)} 字符）：\n" + text


def add_charter(args: dict, ctx: ToolContext) -> str:
    """追加宪章条款：把内容写入工作目录 Coding-Agent.md（追加，不覆盖已有内容）。

    宪章会被注入到后续所有会话的 system prompt 并作为最高优先级约束，
    属于跨会话持久的高影响写操作，故（非 auto_approve 下）需用户确认，默认拒绝。
    """
    text = str(args.get("content", "")).strip()
    if not text:
        raise ToolError(f"charter action=add 需要 content 参数")
    if not ctx.auto_approve:
        if ctx.confirm is None:
            raise ToolError(
                f"写入宪章（{CHARTER_FILENAME}）是跨会话持久的高影响操作，需用户确认，已拒绝"
            )
        if not ctx.confirm(f"写入项目宪章 {CHARTER_FILENAME}：\n{text}"):
            raise ToolError("用户取消了写入宪章")
    p = charter_path(ctx.workdir)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        existing = p.read_text(encoding="utf-8").rstrip() + "\n"
        p.write_text(existing + _ADD_TITLE + text.strip() + "\n", encoding="utf-8")
        verb = "追加"
    else:
        p.write_text(text.strip() + "\n", encoding="utf-8")
        verb = "创建"
    return f"已{verb}宪章 {p}：\n{text.strip()}"


def charter(args: dict, ctx: ToolContext) -> str:
    """charter 工具入口：按 action 分发。"""
    action = str(args.get("action", "read")).strip()
    if action == "read":
        return read_charter(args, ctx)
    if action == "add":
        return add_charter(args, ctx)
    raise ToolError(f"未知 action：{action!r}（支持 read / add）")


CHARTER = Tool(
    name="charter",
    description=(
        "读取或追加项目宪章（工作目录下的 Coding-Agent.md）。"
        "宪章用于固化「无论如何都不能改的内容、必须始终遵守的规范」等关键约束，"
        "它独立于对话历史、不会被上下文压缩遗忘。"
        "当用户明确要求添加/记住某条全局重要规则时，用本工具 action=add 把规则写入宪章；"
        "需要复习已有的关键约束时，用 action=read。写入（add）需用户确认。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "add"],
                "description": "read=查看当前宪章；add=把 content 追加为新的宪章条款",
            },
            "content": {
                "type": "string",
                "description": "当 action=add 时，要固化为宪章的规则/约束正文",
            },
        },
        "required": ["action"],
    },
    handler=charter,
)
