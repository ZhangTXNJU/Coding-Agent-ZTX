"""工具集：读写文件、搜索、命令执行、任务清单。"""
from __future__ import annotations

from .ask_user import ASK_USER
from .bash import (
    BASH,
    BACKGROUND_CANCEL,
    BACKGROUND_LIST,
    BACKGROUND_STATUS,
    BACKGROUND_WAIT,
)
from .charter import CHARTER
from .fetch import FETCH
from .files import APPLY_PATCH, EDIT_FILE, READ_FILE, WRITE_FILE
from .registry import Tool, ToolContext, ToolRegistry
from .search import GLOB, GREP, LIST_DIR
from .skill import USE_SKILL
from .task import TASK
from .todo import TODO_WRITE

_ALL_TOOLS = (READ_FILE, WRITE_FILE, EDIT_FILE, APPLY_PATCH, LIST_DIR, GLOB, GREP, BASH, BACKGROUND_WAIT, BACKGROUND_STATUS, BACKGROUND_CANCEL, BACKGROUND_LIST, TODO_WRITE, ASK_USER, USE_SKILL, TASK, CHARTER, FETCH)


def build_default_registry() -> ToolRegistry:
    """构建包含全部内置工具的注册表。"""
    reg = ToolRegistry()
    for tool in _ALL_TOOLS:
        reg.register(tool)
    return reg


__all__ = [
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "build_default_registry",
    "READ_FILE",
    "WRITE_FILE",
    "EDIT_FILE",
    "APPLY_PATCH",
    "LIST_DIR",
    "GLOB",
    "GREP",
    "BASH",
    "BACKGROUND_WAIT",
    "BACKGROUND_STATUS",
    "BACKGROUND_CANCEL",
    "BACKGROUND_LIST",
    "TODO_WRITE",
    "ASK_USER",
    "USE_SKILL",
    "TASK",
    "CHARTER",
    "FETCH",
]
