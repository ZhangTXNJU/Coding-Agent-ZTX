"""skill 触发工具：use_skill —— 加载指定 skill 的执行指引。

模型判断任务匹配某个 skill 时，先调用本工具拿到该 skill 的「执行指引」，
再严格按其执行。skill 列表（名称 + 用途）由系统提示注入，供模型判断适用性。
"""
from __future__ import annotations

from ..errors import ToolError
from ..skills import skill_prompt
from .registry import Tool, ToolContext


def use_skill(args: dict, ctx: ToolContext) -> str:
    name = str(args.get("name", "")).strip()
    skill = ctx.skills.get(name)
    if skill is None:
        available = "、".join(ctx.skills.names()) or "（无）"
        raise ToolError(f"skill 不存在：{name!r}。可用 skill：{available}")
    return skill_prompt(skill)


USE_SKILL = Tool(
    name="use_skill",
    description=(
        "加载指定 skill 的执行指引。当用户要求执行某个 skill（如代码审查、生成测试、"
        "重构、编写文档、解释代码）时，先调用本工具获取该 skill 的指引，再严格按其执行。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "要加载的 skill 名称（如 code-review / write-tests）",
            },
        },
        "required": ["name"],
    },
    handler=use_skill,
)
