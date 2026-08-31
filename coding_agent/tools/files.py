"""文件工具：read_file / write_file / edit_file / apply_patch。

越界写入（解析后路径落在工作目录之外）一律拦截。
"""
from __future__ import annotations

import re
from pathlib import Path

from ..errors import ToolError
from .registry import Tool, ToolContext

_MAX_READ_BYTES = 256 * 1024  # 单次读取上限，避免把超大文件整个塞进上下文

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _resolve(ctx: ToolContext, path: str, for_write: bool = False) -> Path:
    """把相对路径解析到工作目录下；写操作校验边界。"""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = ctx.workdir / p
    p = p.resolve()
    if for_write:
        root = ctx.workdir.resolve()
        if not p.is_relative_to(root):
            raise ToolError(f"越界写入被拦截：{p} 不在工作目录 {root} 内")
    return p


# --------------------------------------------------------------------------- #
# 各工具 handler（签名统一为 (args: dict, ctx: ToolContext) -> str）
# --------------------------------------------------------------------------- #


def read_file(args: dict, ctx: ToolContext) -> str:
    path = _resolve(ctx, args["path"])
    if not path.is_file():
        raise ToolError(f"文件不存在：{path}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ToolError(f"读取失败：{exc}") from exc
    if b"\x00" in data[:4096]:
        raise ToolError(f"疑似二进制文件，跳过读取：{path}")
    truncated = False
    if len(data) > _MAX_READ_BYTES:
        data = data[:_MAX_READ_BYTES]
        truncated = True
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()

    offset = args.get("offset")
    limit = args.get("limit")
    start = max(0, offset - 1) if offset else 0
    end = start + limit if limit else len(lines)
    result = "\n".join(lines[start:end])
    if truncated:
        result += f"\n…（文件过大，仅显示前 {_MAX_READ_BYTES} 字节）"
    return result


def write_file(args: dict, ctx: ToolContext) -> str:
    path = _resolve(ctx, args["path"], for_write=True)
    content = args["content"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"已写入 {path}（{len(content)} 字符）"


def edit_file(args: dict, ctx: ToolContext) -> str:
    path = _resolve(ctx, args["path"], for_write=True)
    old = args["old_string"]
    new = args["new_string"]
    replace_all = bool(args.get("replace_all", False))
    if not path.is_file():
        raise ToolError(f"文件不存在：{path}")
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise ToolError("old_string 未在文件中找到，未做任何修改")
    if not replace_all and count > 1:
        raise ToolError(
            f"old_string 出现 {count} 次，请提供更长上下文以唯一定位（或 replace_all=true）"
        )
    new_text = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    path.write_text(new_text, encoding="utf-8")
    note = f"替换全部 {count} 处" if replace_all else "替换 1 处"
    return f"已编辑 {path}（{note}）"


def apply_patch(args: dict, ctx: ToolContext) -> str:
    return _apply_patch_text(ctx, args["patch"])


# --------------------------------------------------------------------------- #
# apply_patch 实现：unified diff 解析与应用（单文件 / 多 hunk）
# --------------------------------------------------------------------------- #


def _parse_patch(patch_text: str) -> list[dict]:
    """解析 unified diff → [{"path": str, "hunks": [hunk, ...]}]。

    每个 hunk = (old_start, old_len, new_start, new_len, body_lines)，
    body_lines 保留 '+/-/ ' 前缀；1 起行号在应用时转 0 起。
    """
    files: list[dict] = []
    cur: dict | None = None
    lines = patch_text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        if raw.startswith("--- "):
            cur = {"path": None, "hunks": []}
            files.append(cur)
        elif raw.startswith("+++ ") and cur is not None:
            p = raw[4:]
            if p.startswith("b/"):
                p = p[2:]
            cur["path"] = p
        elif raw.startswith("@@ ") and cur is not None:
            m = _HUNK_RE.match(raw)
            if m:
                old_start = int(m.group(1))
                old_len = int(m.group(2) or 1)
                new_start = int(m.group(3))
                new_len = int(m.group(4) or 1)
                body: list[str] = []
                i += 1
                while i < len(lines) and not (
                    lines[i].startswith("@@ ")
                    or lines[i].startswith("--- ")
                    or lines[i].startswith("diff ")
                ):
                    body.append(lines[i])
                    i += 1
                cur["hunks"].append((old_start, old_len, new_start, new_len, body))
                continue
        i += 1
    return files


def _apply_hunk(file_lines: list[str], hunk: tuple) -> list[str]:
    old_start, old_len, _new_start, _new_len, body = hunk
    old_start -= 1  # 1 起 → 0 起

    # 校验旧侧（上下文 + 删除行必须逐行匹配）
    cursor = old_start
    for line in body:
        if line.startswith("+"):
            continue
        content = line[1:]
        if cursor >= len(file_lines) or file_lines[cursor] != content:
            raise ToolError(f"补丁上下文不匹配（第 {cursor + 1} 行附近），请确认目标文件状态")
        cursor += 1
    if cursor - old_start != old_len:
        raise ToolError("补丁 hunk 行数不一致")

    # 生成新侧
    result: list[str] = []
    cursor = old_start
    for line in body:
        if line.startswith("+"):
            result.append(line[1:])
        elif line.startswith("-"):
            cursor += 1
        else:
            result.append(line[1:])
            cursor += 1
    return file_lines[:old_start] + result + file_lines[cursor:]


def _apply_one_file(ctx: ToolContext, f: dict) -> str:
    path = f["path"]
    if not path:
        raise ToolError("补丁缺少目标文件路径（+++ 行）")
    p = _resolve(ctx, path, for_write=True)
    file_lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    for hunk in f["hunks"]:
        file_lines = _apply_hunk(file_lines, hunk)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 注意：splitlines() 归一化行尾为 \n
    p.write_text("\n".join(file_lines) + ("\n" if file_lines else ""), encoding="utf-8")
    return f"已应用补丁到 {p}"


def _apply_patch_text(ctx: ToolContext, patch_text: str) -> str:
    files = _parse_patch(patch_text)
    if not files:
        raise ToolError("未能从补丁中解析出文件")
    msgs: list[str] = []
    for f in files:
        if not f["hunks"]:
            continue
        msgs.append(_apply_one_file(ctx, f))
    if not msgs:
        raise ToolError("补丁中没有任何 hunk")
    return "\n".join(msgs)


# --------------------------------------------------------------------------- #
# 工具定义（JSON Schema 与 contracts/tools.md 一致）
# --------------------------------------------------------------------------- #

READ_FILE = Tool(
    name="read_file",
    description="读取一个文本文件的内容。路径相对于工作目录。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "offset": {"type": "integer", "description": "起始行（1 起）"},
            "limit": {"type": "integer", "description": "读取行数"},
        },
        "required": ["path"],
    },
    handler=read_file,
)

WRITE_FILE = Tool(
    name="write_file",
    description="创建或整体覆盖一个文件。路径必须在工作目录内。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    handler=write_file,
)

EDIT_FILE = Tool(
    name="edit_file",
    description="将文件中唯一出现的一段文本替换为新文本。old_string 必须精确匹配。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean", "description": "替换所有匹配（默认 false）"},
        },
        "required": ["path", "old_string", "new_string"],
    },
    handler=edit_file,
)

APPLY_PATCH = Tool(
    name="apply_patch",
    description="对工作目录应用 unified diff 补丁。",
    parameters={
        "type": "object",
        "properties": {"patch": {"type": "string"}},
        "required": ["patch"],
    },
    handler=apply_patch,
)
