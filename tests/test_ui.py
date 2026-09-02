"""UI 模块测试：logo 非空、危险命令确认逻辑、任务面板、斜杠补全。"""
from __future__ import annotations

from types import SimpleNamespace

from rich.console import Console

from coding_agent.skills import Skill
from coding_agent.ui import LOGO, UI


def test_logo_nonempty():
    assert LOGO.strip()


def test_ui_constructs():
    assert UI() is not None


def test_confirm_accepts_yes(monkeypatch):
    ui = UI()
    monkeypatch.setattr(ui.console, "input", lambda *a, **k: "y")
    assert ui.confirm("rm -rf /") is True


def test_confirm_rejects_other(monkeypatch):
    ui = UI()
    for answer in ("n", "no", ""):
        monkeypatch.setattr(ui.console, "input", lambda *a, _a=answer, **k: _a)
        assert ui.confirm("rm -rf /") is False


# --------------------------------------------------------------------------- #
# 实时任务面板
# --------------------------------------------------------------------------- #


def test_render_todos_marks_statuses():
    console = Console(record=True, width=100)
    ui = UI(console=console)
    ui.render_todos([
        {"id": 1, "content": "调研现状", "status": "completed"},
        {"id": 2, "content": "写代码", "status": "in_progress"},
        {"id": 3, "content": "跑测试", "status": "pending"},
    ])
    text = console.export_text()
    assert "调研现状" in text
    assert "写代码" in text
    assert "跑测试" in text
    assert "✔" in text and "▶" in text and "☐" in text


def test_render_todos_empty():
    console = Console(record=True, width=100)
    ui = UI(console=console)
    ui.render_todos([])
    assert "任务清单为空" in console.export_text()


def test_tool_result_todo_write_renders_panel():
    console = Console(record=True, width=100)
    ui = UI(console=console)
    ui.bind_context(SimpleNamespace(todos=[{"id": 1, "content": "做某事", "status": "pending"}]))
    ui.tool_result("todo_write", "- [ ] #1 做某事")
    assert "做某事" in console.export_text()


# --------------------------------------------------------------------------- #
# 斜杠补全菜单
# --------------------------------------------------------------------------- #


def _completions(ui, text):
    from prompt_toolkit.document import Document

    completer = ui._pt_session.completer
    doc = Document(text, cursor_position=len(text))
    return list(completer.get_completions(doc, None))


def test_slash_completer_lists_commands():
    ui = UI()
    comps = _completions(ui, "/")
    names = {c.text for c in comps}
    assert {"/help", "/skills", "/skill", "/exit"} <= names
    assert all(c.display_meta for c in comps)  # 每条命令都带用途说明


def _plain(fmt) -> str:
    """把 prompt_toolkit 的 FormattedText 摊平成纯文本。"""
    return "".join(frag for _, frag in fmt)


def test_slash_completer_lists_skills_with_descriptions():
    # 输入 / 即列出全部 skill（不再需要 /skill 前缀）
    ui = UI()
    ui.bind_skills([
        Skill("code-review", "审查代码质量", "指引", "builtin"),
        Skill("create-skill", "创建新 skill", "指引", "builtin"),
    ])
    comps = _completions(ui, "/")
    by_name = {c.text: c.display_meta for c in comps}
    assert "/code-review" in by_name
    assert _plain(by_name["/code-review"]) == "审查代码质量"
    assert "/create-skill" in by_name


def test_slash_completer_prefix_match():
    ui = UI()
    ui.bind_skills([Skill("create-skill", "创建新 skill", "指引", "builtin")])
    comps = _completions(ui, "/create")
    assert [c.text for c in comps] == ["/create-skill"]


def test_slash_completer_fuzzy_match():
    # 子序列模糊匹配：/cr 命中 code-review（c…r）
    ui = UI()
    ui.bind_skills([Skill("code-review", "审查代码质量", "指引", "builtin")])
    names = {c.text for c in _completions(ui, "/cr")}
    assert "/code-review" in names


def test_slash_completer_sorts_prefix_before_subsequence():
    # 前缀命中应排在子序列命中之前
    ui = UI()
    ui.bind_skills([
        Skill("create-skill", "创建新 skill", "指引", "builtin"),
        Skill("code-review", "审查代码质量", "指引", "builtin"),
    ])
    comps = _completions(ui, "/cre")
    assert comps[0].text == "/create-skill"  # 前缀优先于 code-review 的子序列 c…r…e


def test_slash_completer_no_menu_for_plain_text():
    ui = UI()
    assert _completions(ui, "帮我改个 bug") == []


def test_complete_while_typing_is_dynamic_not_constant():
    """回归：补全触发必须是动态过滤器，而非常量 True（常量 True 会常驻预留空白）。"""
    from prompt_toolkit.filters import Condition

    ui = UI()
    cwt = ui._pt_session.complete_while_typing
    assert isinstance(cwt, Condition)  # 动态过滤器，按输入内容决定是否开启
    assert cwt() is False  # 无活跃 app（纯测试环境）时关闭 → 不预留菜单空间


# --------------------------------------------------------------------------- #
# Markdown 流式渲染
# --------------------------------------------------------------------------- #


def test_stream_text_renders_inline_markdown():
    # 非终端（record）下 stream_text 只累积，end_stream 时一次性渲染为 Markdown
    console = Console(record=True, width=80)
    ui = UI(console=console)
    ui.stream_text("**加粗** 与 `行内代码`")
    ui.end_stream()
    text = console.export_text()
    assert "加粗" in text and "行内代码" in text
    assert "**" not in text and "`" not in text  # 原始 markdown 符号被渲染掉


def test_stream_text_renders_code_block():
    console = Console(record=True, width=80)
    ui = UI(console=console)
    ui.stream_text("```python\nprint(1)\n```")
    ui.end_stream()
    text = console.export_text()
    assert "print(1)" in text
    assert "```" not in text  # 代码围栏被渲染成代码块盒子


# --------------------------------------------------------------------------- #
# 高开销区块的流式降级（方案 B：代码围栏 / 表格内暂停每帧全量重排）
# --------------------------------------------------------------------------- #


def test_open_fence_blocked_parity():
    assert UI._open_fence_blocked("```python\nprint(1)") is True      # 未闭合
    assert UI._open_fence_blocked("```python\nprint(1)\n```") is False  # 已闭合
    assert UI._open_fence_blocked("a\n```\nb\n```\nc") is False        # 中段闭合后为普通文本
    assert UI._open_fence_blocked("plain text") is False


def test_open_table_blocked_mid_body():
    mid = "前文\n\n| 列A | 列B |\n|---|------|\n| x | y |"
    closed = mid + "\n\n"
    normal = "表格之后的普通正文内容文字。"
    assert UI._open_table_blocked(mid) is True      # 表体未收尾 → 视为重排中
    assert UI._open_table_blocked(closed) is False  # 空行收尾 → 已定稿
    assert UI._open_table_blocked(normal) is False


def test_stream_text_skips_live_update_in_fence(monkeypatch):
    """身处代码围栏内时不应逐 token 触发 Live 全量重排（只累积 + 延后补画）。"""
    from coding_agent import ui as ui_mod

    calls = []
    class FakeLive:
        def __init__(self, renderable, console=None, refresh_per_second=12):
            self.renderable = renderable
        def start(self): pass
        def update(self, renderable): calls.append(1)
        def stop(self): calls.append("stop")

    monkeypatch.setattr(ui_mod, "Live", FakeLive)
    console = Console(force_terminal=True, width=80)
    ui = UI(console=console)
    # 关键：以整段进入围栏（首个 token 就带 unclosed fence）→ 首帧 start 后应不再每 token update
    for tok in ["```python\n", "for i in range", "(3):\n", "    print(i)\n", "```"]:
        ui.stream_text(tok)
    # 进入围栏期间 update 不应增长（fence 未闭合），结束闭合后应有补帧
    updates_before_close = calls.count(1)
    ui.stream_text("\n")  # 闭合后的空行，离开重排区
    updates_after = calls.count(1)
    assert updates_after > updates_before_close  # 离开围栏时补画了一次
    ui.end_stream()
    assert calls.count("stop") >= 1
