"""UI 模块测试：logo 非空、危险命令确认逻辑。"""
from __future__ import annotations

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
