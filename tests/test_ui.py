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
