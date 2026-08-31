"""搜索工具：list_dir / glob / grep。"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from ..errors import ToolError
from .registry import Tool, ToolContext

_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", ".idea", ".vscode"}
_MAX_RESULTS = 200


def _resolve_dir(ctx: ToolContext, path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = ctx.workdir / p
    return p.resolve()


def _should_skip(p: Path) -> bool:
    return any(part in _SKIP_DIRS for part in p.parts)


def list_dir(args: dict, ctx: ToolContext) -> str:
    path = _resolve_dir(ctx, args.get("path", "."))
    if not path.is_dir():
        raise ToolError(f"目录不存在：{path}")
    entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    if not entries:
        return f"{path} 为空目录"
    lines = [f"{e.name}{'/' if e.is_dir() else ''}" for e in entries]
    return "\n".join(lines)


def glob_search(args: dict, ctx: ToolContext) -> str:
    pattern = args["pattern"]
    matches = sorted(
        p for p in ctx.workdir.glob(pattern) if not _should_skip(p)
    )
    if not matches:
        return f"未匹配到文件：{pattern}"
    lines = [str(p.relative_to(ctx.workdir)) for p in matches[:_MAX_RESULTS]]
    return "\n".join(lines)


def grep_search(args: dict, ctx: ToolContext) -> str:
    pattern = args["pattern"]
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise ToolError(f"非法正则：{exc}") from exc

    root = _resolve_dir(ctx, args.get("path", ".")) if args.get("path") else ctx.workdir.resolve()
    file_glob = args.get("glob")

    results: list[str] = []
    for file in sorted(p for p in root.rglob("*") if p.is_file() and not _should_skip(p)):
        if file_glob and not fnmatch.fnmatch(file.name, file_glob):
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                results.append(f"{file.relative_to(ctx.workdir)}:{lineno}:{line}")
                if len(results) >= _MAX_RESULTS:
                    break
        if len(results) >= _MAX_RESULTS:
            break
    if not results:
        return f"未匹配到：{pattern}"
    return "\n".join(results)


LIST_DIR = Tool(
    name="list_dir",
    description="列出目录下的条目。",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    handler=list_dir,
)

GLOB = Tool(
    name="glob",
    description="按 glob 模式（如 **/*.py）查找文件路径。",
    parameters={
        "type": "object",
        "properties": {"pattern": {"type": "string"}},
        "required": ["pattern"],
    },
    handler=glob_search,
)

GREP = Tool(
    name="grep",
    description="在工作目录内按正则搜索文件内容，返回匹配行与文件位置。",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "description": "限定目录（可选）"},
            "glob": {"type": "string", "description": "限定文件类型（可选）"},
        },
        "required": ["pattern"],
    },
    handler=grep_search,
)
