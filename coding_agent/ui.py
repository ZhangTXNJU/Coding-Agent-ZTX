"""终端 UI：rich 流式渲染 + ASCII logo + 危险命令确认。

纯展示层，不包含任何 agent 编排逻辑；通过回调被 agent / cli 调用。
"""
from __future__ import annotations

import json
import re

from rich.color import Color
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from .tools.ask_user import format_ask_user_result, resolve_answer

try:
    import readline  # noqa: F401  # 启用 input() 的行编辑与历史（macOS 为 libedit）
except ImportError:  # pragma: no cover - 极少数环境无 readline
    pass

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.application import get_app
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style as PTStyle

    _HAS_PROMPT_TOOLKIT = True
except ImportError:  # pragma: no cover - 未安装 prompt_toolkit 时降级为 input()
    _HAS_PROMPT_TOOLKIT = False


if _HAS_PROMPT_TOOLKIT:

    def _build_key_bindings() -> "KeyBindings":
        kb = KeyBindings()

        @kb.add("escape", "enter")  # Esc + Enter 换行（Enter 仍为提交）
        def _(event):
            event.current_buffer.insert_text("\n")

        return kb

    def _typing_slash() -> bool:
        """仅当当前输入以 / 开头时返回 True，用于动态启用补全与预留菜单空间。"""
        try:
            text = get_app().current_buffer.text
        except Exception:  # pragma: no cover - 无活跃 app（如纯渲染测试）时关闭补全
            return False
        return text.lstrip().startswith("/")

    class _SlashCompleter(Completer):
        """斜杠命令补全：输入 / 列出内置命令 + 全部 skill（模糊匹配，含用途说明）。"""

        def __init__(self, commands, skills_getter):
            self._commands = commands  # [(name, description)]，name 已带 / 前缀
            self._skills_getter = skills_getter

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor.lstrip()
            if not text.startswith("/"):
                return
            query = text[1:]  # 去掉斜杠后的查询串

            # 候选：内置命令 + 全部 skill（统一成「去斜杠的名字 + 用途」）
            candidates = [(name.lstrip("/"), desc) for name, desc in self._commands]
            candidates += [
                (skill.name, skill.description) for skill in self._skills_getter()
            ]

            scored = []
            for name, desc in candidates:
                score = _fuzzy_score(query, name)
                if score is not None:
                    scored.append((score, name, desc))
            scored.sort(key=lambda item: (-item[0], item[1]))

            for _score, name, desc in scored:
                yield Completion(
                    "/" + name, start_position=-len(text), display_meta=desc
                )

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


# 内置斜杠命令（名称, 用途说明），用于输入 / 时的补全菜单
_SLASH_COMMANDS = [
    ("/help", "显示帮助"),
    ("/skills", "列出全部可用 skill"),
    ("/skill", "查看/调用某个 skill（/skill <名称>）"),
    ("/sessions", "列出会话历史"),
    ("/continue", "续接会话"),
    ("/clear", "清空当前对话"),
    ("/session", "显示当前会话 ID"),
    ("/exit", "退出"),
]


def _is_subsequence(q: str, t: str) -> bool:
    """q 的字符是否按顺序出现在 t 中（模糊匹配的子序列判定）。"""
    idx = 0
    for ch in t:
        if idx < len(q) and ch == q[idx]:
            idx += 1
    return idx == len(q)


def _fuzzy_score(query: str, target: str) -> int | None:
    """模糊匹配打分：精确 > 前缀 > 子串 > 子序列；不匹配返回 None。分值越大越靠前。"""
    q = query.lower()
    t = target.lower()
    if not q:
        return 3  # 仅输入 / → 全部列出
    if t == q:
        return 4
    if t.startswith(q):
        return 3
    if q in t:
        return 2
    if _is_subsequence(q, t):
        return 1
    return None


class UI:
    """渲染与交互的统一入口。"""

    def __init__(self, verbose: bool = False, console: Console | None = None) -> None:
        self.console = console or Console()
        self.verbose = verbose
        self._skills: list = []  # 斜杠补全用的 skill 列表（由 cli 绑定）
        self._ctx = None  # ToolContext 引用，实时任务面板据此读取 todos
        # markdown 流式渲染状态：累积最终回答文本，终端下用 Live 增量重渲染
        self._md_live: Live | None = None
        self._md_buffer: str = ""
        # 方案 B：身处「代码围栏/表格」等重排代价高的区块时，暂停逐 token 的
        # Live 全量重排（这些区每帧都要重算 Syntax 高亮 / Table 列宽换行）。
        # 只在进入/离开新区块边界或 end_stream 时才补画，避免整套重排抖动。
        self._md_heavy_deferred = False
        # prompt_toolkit 输入会话：常驻 ❯ 提示符 + 上下横线（未安装时降级）
        self._pt_session = None
        if _HAS_PROMPT_TOOLKIT:
            self._pt_session = PromptSession(
                history=InMemoryHistory(),
                style=PTStyle.from_dict(
                    {
                        "prompt": "bold #00d26a",
                        "line": "#3f3f46",
                        "hint": "#71717a",
                    }
                ),
                key_bindings=_build_key_bindings(),
                complete_while_typing=Condition(_typing_slash),
                completer=_SlashCompleter(_SLASH_COMMANDS, lambda: self._skills),
            )

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

    # -- Markdown 流式渲染：重排代价高的区块降级 -------------------------- #

    @staticmethod
    def _open_fence_blocked(buffer: str) -> bool:
        """是否处于未闭合的代码围栏内（首尾为一对 ``` 或 ~~~ 之间）。"""
        in_fence = False
        for line in buffer.split("\n"):
            s = line.strip()
            if s.startswith("~~~") or s.startswith("```"):
                # 围栏以行首连续 3 个反引号/波浪号为界
                if len(s) >= 3 and s[:3] in ("```", "~~~"):
                    in_fence = not in_fence
        return in_fence

    @staticmethod
    def _open_table_blocked(buffer: str) -> bool:
        """是否处于「尚未收尾、可能还在追加行」的 markdown 表体。

        界定：从缓冲末尾倒推，找到一个空行作为分界，把「最后一个非空段」
        视作还在形成中的区块。若该段的剩余内容仍是连续的表行/分隔行，
        且尚未被空行或非表内容切断，则认为表格可能继续接收新行 → 重排代价高。
        """
        # 只考察最后一个被空行隔开的“开放段”；缓冲若以空行结尾则已闭合。
        if buffer.endswith("\n\n") or buffer.endswith("\n \n"):
            return False
        head, _, tail = buffer.rpartition("\n\n")
        if "\n\n" not in buffer:
            # 整段只有一块：尚无空行，仍需考察
            head, tail = "", buffer
        lines = tail.split("\n")
        # 非空行才参与判断（尾空行视作已结束）
        non_empty = [ln for ln in lines if ln.strip() != ""]
        if not non_empty:
            return False
        # 是否为“表格风格”的行（行首或含竖线分隔）
        def is_row(ln: str) -> bool:
            s = ln.strip()
            return s.startswith("|") or (s.count("|") >= 1 and "|" in s)
        seg_rows = is_row(non_empty[-1])
        if not seg_rows:
            return False
        # 段内若含有表头分隔行（|-...|），或仅表头本身，都算重排中
        has_sep = any(re.match(r"^\s*\|?[\s:|-]+\|?\s*$", ln) and "-" in ln for ln in non_empty)
        # 只要最后若干行皆为表格行且段内出现过“|…|”结构即可判为重排中
        return has_sep or len(non_empty) >= 2

    def stream_text(self, chunk: str) -> None:
        """逐 token 流式输出：累积为 Markdown，终端下用 Live 增量重渲染。

        相比直接打印原始 chunk，这里把 **粗体**、`行内代码`、``` 代码块、# 标题、
        列表、表格等 Markdown 语法渲染成真正的终端样式（加粗/高亮/配色），而非
        带 * 号的纯文本。非终端（重定向/测试）只累积，待 end_stream() 一次性渲染。

        优化（方案 B）：代码围栏、数据表格这类多行、需逐帧重算布局的区块，
        在尚未描完前暂停每 token 的全量 Live 重排；只在离开该区块或结束时补画，
        避免整套 Markdown 布局（Syntax 高亮 / Table 列宽换行）在高频下反复抖动。
        """
        self._md_buffer += chunk
        if not self.console.is_terminal:
            return
        if self._md_live is None:
            self._md_live = Live(Markdown(""), console=self.console, refresh_per_second=12)
            self._md_live.start()
        deferred = (
            self._open_fence_blocked(self._md_buffer)
            or self._open_table_blocked(self._md_buffer)
        )
        if deferred:
            # 身处高开销区块：暂缓即时重排，仅标记待离开后补画
            self._md_heavy_deferred = True
            return
        # 已离开（或从未进入）高开销区块：渲染到最新并复位延迟标记
        self._md_heavy_deferred = False
        self._md_live.update(Markdown(self._md_buffer))

    def _end_stream(self) -> None:
        """结束当前 markdown 流式渲染：渲染最后一帧并复位状态（幂等）。"""
        if self._md_live is not None:
            # 若尚有被延迟的高开销区块，stop 前强制补一帧，确保不丢尾部内容
            if self._md_heavy_deferred:
                self._md_live.update(Markdown(self._md_buffer))
            self._md_live.stop()
            self._md_live = None
            self._md_buffer = ""
            self._md_heavy_deferred = False
        elif self._md_buffer:
            # 非终端路径：缓冲的完整回答在此一次性渲染
            self.console.print(Markdown(self._md_buffer))
            self._md_buffer = ""
            self._md_heavy_deferred = False

    def end_stream(self) -> None:
        """结束当前流式回答并另起一行（cli 在每次 agent.run 返回后调用）。"""
        self._end_stream()
        self.console.print()

    def tool_call(self, name: str, args: dict) -> None:
        """渲染一次工具调用（面板展示工具名 + 参数）。"""
        self._end_stream()
        if name in ("todo_write", "ask_user"):
            # todo_write 改由 tool_result 渲染；ask_user 由下方交互提示自渲染，均不重复刷 JSON
            return
        self.console.print()  # 结束上一段流式文本
        body = Text(name, style="bold cyan")
        if args:
            body.append("\n" + json.dumps(args, ensure_ascii=False, indent=2), style="dim")
        self.console.print(
            Panel(body, title="工具调用", title_align="left", border_style="cyan")
        )

    def tool_result(self, name: str, result: str) -> None:
        """渲染工具结果（截断展示，避免刷屏）。"""
        self._end_stream()
        if name == "todo_write" and self._ctx is not None:
            self.render_todos(self._ctx.todos)
            return
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

    def render_todos(self, todos: list) -> None:
        """渲染实时任务清单面板：随 todo_write 调用刷新，标记完成/进行中/待办。"""
        if not todos:
            self.console.print(
                Panel(
                    Text("任务清单为空", style="dim"),
                    title="任务清单",
                    title_align="left",
                    border_style="bright_black",
                )
            )
            return
        body = Text()
        for t in todos:
            status = t.get("status", "pending")
            content = str(t.get("content", ""))
            if status == "completed":
                body.append("✔ ", style="bold green")
                body.append(content, style="green strike")
            elif status == "in_progress":
                body.append("▶ ", style="bold yellow")
                body.append(content, style="yellow")
            else:
                body.append("☐ ", style="dim")
                body.append(content, style="default")
            body.append("\n")
        done = sum(1 for t in todos if t.get("status") == "completed")
        self.console.print(
            Panel(
                body,
                title=f"任务清单 · {done}/{len(todos)} 完成",
                title_align="left",
                border_style="cyan",
            )
        )

    def info(self, text: str) -> None:
        self._end_stream()
        self.console.print(text, style="dim")

    def error(self, text: str) -> None:
        self._end_stream()
        self.console.print(f"[bold red]错误[/] {text}")

    def render_sessions(self, sessions) -> None:
        """以表格列出会话历史（序号/ID/时间/标题/消息数）。"""
        from rich.table import Table

        if not sessions:
            self.info("暂无会话历史。")
            return
        table = Table(title="会话历史", title_justify="left", border_style="dim", pad_edge=False)
        table.add_column("#", justify="right", style="dim", no_wrap=True)
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("时间", style="dim", no_wrap=True)
        table.add_column("标题")
        table.add_column("消息", justify="right", style="dim", no_wrap=True)
        for i, s in enumerate(sessions, 1):
            table.add_row(str(i), s.id, s.created_at, s.title or "（无标题）", str(s.message_count))
        self.console.print(table)

    def render_skills(self, skills) -> None:
        """以表格列出全部可用 skill（名称/来源/用途）。"""
        from rich.table import Table

        if not skills:
            self.info("暂无可用 skill。")
            return
        table = Table(title="可用 skill", title_justify="left", border_style="dim", pad_edge=False)
        table.add_column("名称", style="cyan", no_wrap=True)
        table.add_column("来源", style="dim", no_wrap=True)
        table.add_column("用途")
        for s in skills:
            src = "内置" if s.source == "builtin" else "自定义"
            table.add_row(s.name, src, s.description)
        self.console.print(table)

    def render_skill(self, skill) -> None:
        """展示单个 skill 的用途与完整执行指引。"""
        body = Text()
        body.append(skill.description + "\n\n", style="bold")
        body.append(skill.instructions, style="default")
        source = "内置" if skill.source == "builtin" else "自定义"
        self.console.print(
            Panel(body, title=f"skill · {skill.name} · {source}", title_align="left", border_style="cyan")
        )

    def bind_context(self, ctx) -> None:
        """绑定 ToolContext，实时任务面板据此读取 todos。"""
        self._ctx = ctx

    def bind_skills(self, skills) -> None:
        """绑定当前可用 skill 列表，斜杠补全菜单据此展示。"""
        self._skills = list(skills)

    def help(self) -> None:
        self.console.print(
            "[bold]可用命令：[/]\n"
            "  [cyan]/help[/]        显示本帮助\n"
            "  [cyan]/skills[/]      列出全部可用 skill（内置 + 自定义）\n"
            "  [cyan]/skill[/]       查看某个 skill 的指引（/skill <名称>）\n"
            "  [cyan]/sessions[/]    列出全部会话历史\n"
            "  [cyan]/continue[/]    续接会话（/continue <ID或序号>，缺省为最新）\n"
            "  [cyan]/clear[/]       清空当前对话上下文\n"
            "  [cyan]/exit[/]        退出（或输入 exit / quit）\n"
            "  [cyan]/<skill名>[/]    直接调用 skill（可追加自然语言，如 /code-review 检查 src/）\n"
            "  [dim]输入 / 弹出命令与 skill 补全菜单（模糊匹配 + 用途说明，Tab 补全）[/]\n"
            "  [dim]直接输入自然语言任务 → 交给 agent 执行（匹配 skill 时自动调用）[/]"
        )

    # -- 交互 --------------------------------------------------------------- #

    def prompt(self) -> str:
        """读取一行输入：常驻 ❯ 提示符 + 上下横线（prompt_toolkit）。"""
        self._end_stream()
        if self._pt_session is not None:
            self.console.print("─" * (self.console.width or 80), style="dim")
            return self._pt_session.prompt(
                message=FormattedText([("class:prompt", "❯ ")]),
                rprompt=FormattedText([("class:hint", " / 命令菜单 · /help · /exit ")]),
                bottom_toolbar=self._bottom_toolbar,
                # complete_while_typing 是动态 Condition：仅在输入以 / 开头时
                # 才预留菜单空间并弹出补全，普通文本输入不占用下方空白。
            )
        return self.console.input("[bold green]❯ [/]")

    def _bottom_toolbar(self):
        """输入框底部：单条横线（由 prompt_toolkit 渲染，不受回删影响）。"""
        width = get_app().output.get_size().columns
        return [("class:line", "─" * width)]

    def confirm(self, command: str) -> bool:
        """危险命令确认：[y/N] 提示，仅显式同意才放行。"""
        self.console.print()
        self.console.print(
            Panel(command, title="⚠ 危险命令，确认执行？", title_align="left", border_style="yellow")
        )
        ans = self.console.input("[bold yellow]  [y/N] [/]").strip().lower()
        return ans in ("y", "yes")

    def ask_user(self, questions: list) -> str:
        """交互式向用户提问（ask_user 工具回调）：逐题渲染选项、收集选择、返回结果文本。"""
        answers = [(q, self._ask_one(q, i)) for i, q in enumerate(questions, 1)]
        return format_ask_user_result(answers)

    def _ask_one(self, question: dict, index: int) -> str:
        """渲染单个问题并收集答案，返回「已解析答案」文本。"""
        header = str(question.get("header") or "").strip()
        text = str(question.get("question") or "").strip()
        options = question.get("options") or []
        multi = bool(question.get("multiSelect", False))

        body = Text()
        if text:
            body.append(text + "\n\n", style="bold")
        for n, opt in enumerate(options, 1):
            label = str(opt.get("label") or "").strip() or f"选项 {n}"
            desc = str(opt.get("description") or "").strip()
            body.append(f"{n}. ", style="cyan")
            body.append(label, style="bold")
            if desc:
                body.append(f"  —— {desc}", style="dim")
            body.append("\n")

        title = f"提问 Q{index}"
        if header:
            title += f" · {header}"
        self.console.print()
        self.console.print(
            Panel(body, title=title, title_align="left", border_style="magenta")
        )
        hint = "可多选：输入序号，逗号分隔（如 1,3）" if multi else "输入序号（如 1），或直接输入自定义答案"
        try:
            raw = self.console.input(f"[bold magenta]  你的选择[/]（{hint}）: ")
        except (EOFError, KeyboardInterrupt):
            return "（非交互环境，未获得回答）"
        return resolve_answer(question, raw)
