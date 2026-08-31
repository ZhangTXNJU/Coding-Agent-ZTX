"""模型输出解析：tool_call arguments 的 JSON 解析与修复。

模型生成工具参数时常带 markdown 代码块、尾随逗号、单引号、尾部垃圾甚至截断，
这里做「提取 → 修复 → 解析」三级处理，失败抛 ParsingError 由主循环回传降级。
"""
from __future__ import annotations

import json
import re

from .errors import ParsingError


def _extract_first_object(s: str) -> str:
    """从字符串中提取第一个平衡的 JSON 对象（剥离前缀说明 / 尾部垃圾）。"""
    start = s.find("{")
    if start == -1:
        return s
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    # 未闭合：返回从 { 到结尾，交给 _repair 尝试补全
    return s[start:]


def _repair(s: str) -> dict:
    """对无法直接解析的片段做启发式修复。"""
    attempts = [s]
    if s.lstrip().startswith("{") and s.count("{") > s.count("}"):
        attempts.append(s + "}")  # 截断补全
    attempts.append(s.replace("'", '"'))  # 单引号 → 双引号
    attempts.append(re.sub(r",\s*([}\]])", r"\1", s))  # 去尾随逗号
    attempts.append(re.sub(r",\s*([}\]])", r"\1", s.replace("'", '"')))
    for a in attempts:
        try:
            obj = json.loads(a)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ParsingError(f"无法解析工具参数 JSON：{s[:200]!r}")


def parse_tool_arguments(arguments: str) -> dict:
    """把 tool_call 的 arguments 字符串解析为 dict。空值返回 {}。"""
    if not arguments or not arguments.strip():
        return {}
    raw = arguments.strip()
    # 剥离 markdown 代码块包裹
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = _extract_first_object(raw)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        obj = _repair(raw)
    if isinstance(obj, dict):
        return obj
    raise ParsingError(f"工具参数不是 JSON 对象：{arguments[:100]!r}")
