"""项目宪章：工作目录下 Coding-Agent.md 的读取 helper。

仿 Claude Code 的 CLAUDE.md 机制——把「无论如何不能动的内容 / 必须遵守的规范」
等关键约束固化到一个独立于对话历史的文件里。conversation 压缩（compact()）
不会触及这些规则：它们要么在启动时被注入 system prompt（永不参与裁剪），
要么由 agent 通过 charter 工具随时读取。

约定：宪章文件固定在每个工作目录下的 Coding-Agent.md。

本模块只含纯 helper 与常量，不 import 工具层，避免与 tools/__init__ 循环依赖；
charter 工具本身见 tools/charter.py。
"""
from __future__ import annotations

from pathlib import Path

CHARTER_FILENAME = "Coding-Agent.md"


def charter_path(workdir: Path) -> Path:
    """宪章文件路径：工作目录 + Coding-Agent.md。"""
    wd = Path(workdir).expanduser().resolve()
    return wd / CHARTER_FILENAME


def charter_exists(workdir: Path) -> bool:
    """工作目录是否存在宪章文件。"""
    return charter_path(workdir).is_file()


def load_charter(workdir: Path) -> tuple[str, bool]:
    """读取宪章：返回 (宪章全文, 是否有非空正文)。

    宪章文件不存在或为空时返回 ("", False)。启动注入用全文。
    """
    p = charter_path(workdir)
    if not p.is_file():
        return "", False
    text = p.read_text(encoding="utf-8")
    return text, bool(text.strip())
