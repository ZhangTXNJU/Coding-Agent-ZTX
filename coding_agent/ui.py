"""终端 UI：rich 流式渲染 + ASCII logo + 危险命令确认。

纯展示层，不包含任何 agent 编排逻辑；通过回调被 agent / cli 调用。
"""
from __future__ import annotations

import json

from rich.color import Color
from rich.console import Console
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

try:
    import readline  # noqa: F401  # 启用 input() 的行编辑与历史（macOS 为 libedit）
except ImportError:  # pragma: no cover - 极少数环境无 readline
    pass

# figlet 风格的 "CA" 单色 logo（配合下方渐变渲染）
LOGO = (
    "   ___    _    \n"
    "  / __\\  /_\\   \n"
    " / /    //_\\\\  \n"
    "/ /___ /  _  \\ \n"
    "\\____/ \\_/ \\_/ "
)

# 渐变起止色（亮青 → 紫）
_GRAD_START = (0, 210, 255)
_GRAD_END = (180, 80, 255)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


class UI:
    """渲染与交互的统一入口。"""

    def __init__(self, verbose: bool = False, console: Console | None = None) -> None:
        self.console = console or Console()
        self.verbose = verbose

    # -- 渲染 --------------------------------------------------------------- #

    def _gradient_logo(self) -> Text:
        lines = LOGO.splitlines()
        out = Text()
        n = max(len(lines) - 1, 1)
        for i, line in enumerate(lines):
            r, g, b = _lerp(_GRAD_START, _GRAD_END, i / n)
            out.append(line, Style(color=Color.from_rgb(r, g, b), bold=True))
            out.append("\n")
        return out

    def logo(self, provider: str = "", model: str = "", workdir: str = "") -> None:
        """打印启动 logo 与版本信息。"""
        self.console.print(self._gradient_logo())
        self.console.print("Coding Agent · 自研编程智能体", style="bold", justify="center")
        meta = f"{provider}/{model}" if provider else ""
        if meta and workdir:
            meta += f" · 工作目录 {workdir}"
        if meta:
            self.console.print(meta, style="dim", justify="center")
        self.console.print()

    def stream_text(self, chunk: str) -> None:
        """逐 token 流式输出（不解析 markup，避免代码片段中的字符被误读）。"""
        self.console.print(chunk, end="", markup=False, soft_wrap=True)

    def tool_call(self, name: str, args: dict) -> None:
        """渲染一次工具调用（面板展示工具名 + 参数）。"""
        self.console.print()  # 结束上一段流式文本
        body = Text(name, style="bold cyan")
        if args:
            body.append("\n" + json.dumps(args, ensure_ascii=False, indent=2), style="dim")
        self.console.print(
            Panel(body, title="工具调用", title_align="left", border_style="cyan")
        )

    def tool_result(self, name: str, result: str) -> None:
        """渲染工具结果（截断展示，避免刷屏）。"""
        max_chars = 600
        shown = (
            result
            if len(result) <= max_chars
            else result[:max_chars] + f"\n…（共 {len(result)} 字符，已截断）"
        )
        self.console.print(
            Panel(
                Text(shown, style="dim"),
                title=f"结果 · {name}",
                title_align="left",
                border_style="bright_black",
            )
        )

    def info(self, text: str) -> None:
        self.console.print(text, style="dim")

    def error(self, text: str) -> None:
        self.console.print(f"[bold red]错误[/] {text}")

    def help(self) -> None:
        self.console.print(
            "[bold]可用命令：[/]\n"
            "  [cyan]/help[/]     显示本帮助\n"
            "  [cyan]/clear[/]    清空当前对话上下文\n"
            "  [cyan]/session[/]  显示当前会话 ID\n"
            "  [cyan]/exit[/]     退出（或输入 exit / quit）\n"
            "  [dim]直接输入自然语言任务 → 交给 agent 执行[/]"
        )

    # -- 交互 --------------------------------------------------------------- #

    def prompt(self) -> str:
        return self.console.input("[bold green]❯ [/]")

    def confirm(self, command: str) -> bool:
        """危险命令确认：[y/N] 提示，仅显式同意才放行。"""
        self.console.print()
        self.console.print(
            Panel(command, title="⚠ 危险命令，确认执行？", title_align="left", border_style="yellow")
        )
        ans = self.console.input("[bold yellow]  [y/N] [/]").strip().lower()
        return ans in ("y", "yes")
