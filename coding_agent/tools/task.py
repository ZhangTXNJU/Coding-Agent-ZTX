"""subagent 委托工具：task —— 把独立子任务交给子 agent 独立完成。

子 agent 在同进程内阻塞式运行，独立上下文，只回传最终结论；
中间工具调用与输出不进入主对话。子 agent 无法再调用 task（禁止嵌套）。
"""
from __future__ import annotations

from ..errors import ToolError
from .registry import Tool, ToolContext


def run_subagent(args: dict, ctx: ToolContext) -> str:
    prompt = str(args.get("prompt", "")).strip()
    if not prompt:
        raise ToolError("task 缺少 prompt（需给出自包含的子任务指令）")
    if ctx.spawn_subagent is None:
        raise ToolError("子 agent 不可用（当前环境未配置委托能力）")
    return ctx.spawn_subagent(prompt)


TASK = Tool(
    name="task",
    description=(
        "把一块相对独立的子任务委托给一个子 agent 在独立上下文中完成，只回传最终结论"
        "（中间过程不进入主对话）。适合：需要多轮读/搜/改、会产生大量中间输出的工作，"
        "或与主任务解耦、可独立完成的一块。prompt 必须自包含（含目标文件、约束、期望产出）。"
        "不适合：读单个文件、简单查找等一步即可完成的操作。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "给子 agent 的自包含任务指令（含目标、约束、期望产出）",
            },
        },
        "required": ["prompt"],
    },
    handler=run_subagent,
)
