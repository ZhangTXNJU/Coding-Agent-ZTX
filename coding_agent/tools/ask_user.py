"""ask_user 工具：需求不明确时向用户提问，让用户在给定选项中选择。

仿 Claude Code 的 AskUserQuestion：agent 面对多种都合理的方案、或需求表述含糊时，
调用本工具把「问题 + 选项」呈现给用户，等用户选定后再继续，而不是自行猜测。

交互部分（渲染 + 收集输入）由 UI 层通过 ToolContext.ask_user 回调注入；
本模块同时提供纯函数 resolve_answer / format_ask_user_result，把「原始输入 → 答案文本」
的解析逻辑抽出来，便于单元测试（UI 的终端交互不在测试范围内）。
"""
from __future__ import annotations

from ..errors import ToolError
from .registry import Tool, ToolContext


def resolve_answer(question: dict, raw: str) -> str:
    """把用户原始输入解析为「已选定项」文本。

    - 纯数字或逗号分隔的数字 → 映射为对应选项的 label（多选用「；」连接）
    - 其它非空文本 → 视为用户自定义答案，原样返回
    - 空输入 → 「（未回答）」
    """
    options = question.get("options", []) or []
    raw = (raw or "").strip().replace("，", ",")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if parts and all(p.isdigit() for p in parts):
        labels = []
        for p in parts:
            idx = int(p) - 1
            if 0 <= idx < len(options):
                label = str(options[idx].get("label", "")).strip()
                if label:
                    labels.append(label)
        return "；".join(labels) if labels else "（无效序号）"
    return raw or "（未回答）"


def format_ask_user_result(answers: list[tuple[dict, str]]) -> str:
    """把 [(问题 dict, 已解析答案)] 渲染成回传给 LLM 的文本结果。"""
    if not answers:
        return "（未提问）"
    lines = ["用户回答："]
    for i, (q, resolved) in enumerate(answers, 1):
        header = str(q.get("header") or q.get("question", "")).strip()
        lines.append(f"  Q{i}【{header}】: {resolved}")
    return "\n".join(lines)


def ask_user(args: dict, ctx: ToolContext) -> str:
    """工具入口：把问题交给交互回调（UI），返回用户的最终选择。"""
    questions = args.get("questions") or []
    if not questions:
        raise ToolError("ask_user 至少需要一个问题")
    if ctx.ask_user is None:
        raise ToolError("当前环境不支持交互提问（非交互终端）")
    return ctx.ask_user(questions)


ASK_USER = Tool(
    name="ask_user",
    description=(
        "向用户提问，让用户在给定选项中选择一个或多个方案。"
        "当需求不明确、或存在多种都合理的实现/技术方案需要用户拍板时，"
        "先调用本工具，等用户选定后再继续，不要自行猜测。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "description": "要问用户的一个或多个问题",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "完整的问题描述（说明需要确认什么）",
                        },
                        "header": {
                            "type": "string",
                            "description": "简短标签（≤12 字），用于标识该问题",
                        },
                        "multiSelect": {
                            "type": "boolean",
                            "description": "是否允许多选（默认单选）",
                        },
                        "options": {
                            "type": "array",
                            "description": "供用户选择的方案（通常 2~4 个，第一个为推荐项）",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string", "description": "选项名称（简洁）"},
                                    "description": {
                                        "type": "string",
                                        "description": "选项说明或选择后的影响",
                                    },
                                },
                                "required": ["label"],
                            },
                        },
                    },
                    "required": ["question", "options"],
                },
            }
        },
        "required": ["questions"],
    },
    handler=ask_user,
)
