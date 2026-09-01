"""工具系统测试：读写文件 / 搜索 / 命令执行 / 任务清单 / 注册表。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from coding_agent.errors import ToolError
from coding_agent.tools import (
    APPLY_PATCH,
    BASH,
    EDIT_FILE,
    GLOB,
    GREP,
    LIST_DIR,
    READ_FILE,
    TODO_WRITE,
    WRITE_FILE,
    build_default_registry,
)
from coding_agent.tools.bash import dangerous_reason
from coding_agent.tools.registry import ToolContext, ToolRegistry


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(workdir=tmp_path)


# --------------------------------------------------------------------------- #
# read_file / write_file
# --------------------------------------------------------------------------- #


def test_write_and_read_roundtrip(ctx):
    WRITE_FILE.handler({"path": "a/b.txt", "content": "hello\nworld"}, ctx)
    assert (ctx.workdir / "a" / "b.txt").read_text() == "hello\nworld"
    assert READ_FILE.handler({"path": "a/b.txt"}, ctx) == "hello\nworld"


def test_read_file_offset_limit(ctx):
    (ctx.workdir / "f.txt").write_text("l1\nl2\nl3\nl4\n")
    assert READ_FILE.handler({"path": "f.txt", "offset": 2, "limit": 2}, ctx) == "l2\nl3"


def test_read_missing_file_raises(ctx):
    with pytest.raises(ToolError):
        READ_FILE.handler({"path": "nope.txt"}, ctx)


def test_write_file_boundary_relative(ctx):
    with pytest.raises(ToolError):
        WRITE_FILE.handler({"path": "../outside.txt", "content": "x"}, ctx)


def test_write_file_boundary_absolute(ctx, tmp_path):
    outside = tmp_path.parent / "outside.txt"
    with pytest.raises(ToolError):
        WRITE_FILE.handler({"path": str(outside), "content": "x"}, ctx)


# --------------------------------------------------------------------------- #
# edit_file
# --------------------------------------------------------------------------- #


def test_edit_file_unique_replace(ctx):
    (ctx.workdir / "f.txt").write_text("abc 123 abc")
    EDIT_FILE.handler({"path": "f.txt", "old_string": "123", "new_string": "456"}, ctx)
    assert (ctx.workdir / "f.txt").read_text() == "abc 456 abc"


def test_edit_file_multiple_matches_raises_without_replace_all(ctx):
    (ctx.workdir / "f.txt").write_text("a a a")
    with pytest.raises(ToolError):
        EDIT_FILE.handler({"path": "f.txt", "old_string": "a", "new_string": "b"}, ctx)


def test_edit_file_replace_all(ctx):
    (ctx.workdir / "f.txt").write_text("a a a")
    EDIT_FILE.handler(
        {"path": "f.txt", "old_string": "a", "new_string": "b", "replace_all": True}, ctx
    )
    assert (ctx.workdir / "f.txt").read_text() == "b b b"


def test_edit_file_missing_old_string_raises(ctx):
    (ctx.workdir / "f.txt").write_text("hello")
    with pytest.raises(ToolError):
        EDIT_FILE.handler({"path": "f.txt", "old_string": "zzz", "new_string": "y"}, ctx)


# --------------------------------------------------------------------------- #
# apply_patch
# --------------------------------------------------------------------------- #

PATCH = """--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 def greet():
-    print("hi")
+    print("hello")
     return 1
"""


def test_apply_patch_modifies_file(ctx):
    (ctx.workdir / "foo.py").write_text('def greet():\n    print("hi")\n    return 1\n')
    APPLY_PATCH.handler({"patch": PATCH}, ctx)
    assert (ctx.workdir / "foo.py").read_text() == 'def greet():\n    print("hello")\n    return 1\n'


def test_apply_patch_creates_new_file(ctx):
    patch = """--- /dev/null
+++ b/new.txt
@@ -0,0 +1,1 @@
+hello
"""
    APPLY_PATCH.handler({"patch": patch}, ctx)
    assert (ctx.workdir / "new.txt").read_text() == "hello\n"


def test_apply_patch_context_mismatch_raises(ctx):
    (ctx.workdir / "foo.py").write_text("totally different\n")
    with pytest.raises(ToolError):
        APPLY_PATCH.handler({"patch": PATCH}, ctx)


def test_apply_patch_no_hunks_raises(ctx):
    with pytest.raises(ToolError):
        APPLY_PATCH.handler({"patch": "just some text\nno diff here\n"}, ctx)


# --------------------------------------------------------------------------- #
# list_dir / glob / grep
# --------------------------------------------------------------------------- #


def test_list_dir_marks_dirs(ctx):
    (ctx.workdir / "d").mkdir()
    (ctx.workdir / "a.txt").write_text("x")
    lines = LIST_DIR.handler({"path": "."}, ctx).splitlines()
    assert "a.txt" in lines
    assert "d/" in lines


def test_glob_finds_files(ctx):
    (ctx.workdir / "pkg").mkdir()
    (ctx.workdir / "pkg" / "a.py").write_text("")
    (ctx.workdir / "pkg" / "b.txt").write_text("")
    out = GLOB.handler({"pattern": "**/*.py"}, ctx)
    assert "pkg/a.py" in out
    assert "b.txt" not in out


def test_grep_returns_file_line(ctx):
    (ctx.workdir / "x.py").write_text("foo\nbar foo\nbaz\n")
    out = GREP.handler({"pattern": "foo"}, ctx)
    assert "x.py:1:foo" in out
    assert "x.py:2:bar foo" in out
    assert "baz" not in out


# --------------------------------------------------------------------------- #
# bash + dangerous command detection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /tmp/x",
        "rm -fr .",
        "sudo rm -rf /",
        "git push --force origin main",
        "mkfs.ext4 /dev/sda1",
    ],
)
def test_dangerous_reason_detects(cmd):
    assert dangerous_reason(cmd) is not None


@pytest.mark.parametrize("cmd", ["ls -la", "echo hello", "pytest tests/", "git status"])
def test_dangerous_reason_passes_safe(cmd):
    assert dangerous_reason(cmd) is None


def test_run_bash_returns_output(ctx):
    out = BASH.handler({"command": "echo hello"}, ctx)
    assert "exit_code: 0" in out
    assert "hello" in out


def test_run_bash_dangerous_denied_by_default(ctx):
    with pytest.raises(ToolError):
        BASH.handler({"command": "rm -rf /tmp/x"}, ctx)


def test_run_bash_dangerous_allowed_when_confirmed(ctx, monkeypatch):
    executed: list[str] = []

    def fake_run(command, **kwargs):
        executed.append(command)
        return NS(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("coding_agent.tools.bash.subprocess.run", fake_run)
    ctx.confirm = lambda cmd: True  # 模拟用户确认
    out = BASH.handler({"command": "rm -rf /tmp/x"}, ctx)
    assert executed == ["rm -rf /tmp/x"]  # 确认通过后真正执行
    assert "exit_code: 0" in out


def test_run_bash_timeout_raises(ctx):
    # sleep 1 但 0.2s 即超时 → TimeoutExpired → ToolError
    with pytest.raises(ToolError):
        BASH.handler({"command": "sleep 1", "timeout": 0.2}, ctx)


# --------------------------------------------------------------------------- #
# todo_write
# --------------------------------------------------------------------------- #


def test_todo_write_updates_context(ctx):
    out = TODO_WRITE.handler(
        {"todos": [{"id": 1, "content": "写代码", "status": "in_progress"}]}, ctx
    )
    assert "- [→] #1 写代码" in out
    assert ctx.todos[0]["status"] == "in_progress"


def test_todos_to_text_renders_and_empty():
    from coding_agent.tools.todo import todos_to_text

    assert todos_to_text([]) == ""
    text = todos_to_text([
        {"id": 1, "content": "写代码", "status": "in_progress"},
        {"id": 2, "content": "跑测试", "status": "completed"},
    ])
    assert "当前任务清单" in text
    assert "- [→] #1 写代码" in text
    assert "- [x] #2 跑测试" in text


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #


def test_registry_to_openai_tools():
    reg = build_default_registry()
    tools = reg.to_openai_tools()
    names = {t["function"]["name"] for t in tools}
    assert {
        "read_file", "write_file", "edit_file", "apply_patch",
        "list_dir", "glob", "grep", "bash", "todo_write",
    } <= names
    for t in tools:
        assert t["type"] == "function"
        assert t["function"]["parameters"]["type"] == "object"


def test_registry_run_dispatches(ctx):
    reg = build_default_registry()
    out = reg.run("write_file", {"path": "z.txt", "content": "hi"}, ctx)
    assert "已写入" in out
    assert (ctx.workdir / "z.txt").read_text() == "hi"


def test_registry_unknown_tool_raises(ctx):
    reg = build_default_registry()
    with pytest.raises(ToolError):
        reg.run("does_not_exist", {}, ctx)


def test_registry_duplicate_raises():
    reg = ToolRegistry()
    reg.register(READ_FILE)
    with pytest.raises(ValueError):
        reg.register(READ_FILE)


# --------------------------------------------------------------------------- #
# 健壮性：大文件拒读 / 非交互执行
# --------------------------------------------------------------------------- #


def test_read_file_rejects_oversized(ctx):
    (ctx.workdir / "big.txt").write_text("x" * (256 * 1024 + 1))
    with pytest.raises(ToolError, match="过大"):
        READ_FILE.handler({"path": "big.txt"}, ctx)


def test_read_file_oversized_with_offset_allowed(ctx):
    # 指定 offset/limit 分片读取超限文件时不应被拒绝
    (ctx.workdir / "big.txt").write_text("line\n" * 60_000)  # > 256KB
    out = READ_FILE.handler({"path": "big.txt", "offset": 3, "limit": 2}, ctx)
    assert out.splitlines() == ["line", "line"]


def test_run_bash_is_noninteractive(ctx, monkeypatch):
    import subprocess as sp

    captured: dict = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return NS(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("coding_agent.tools.bash.subprocess.run", fake_run)
    out = BASH.handler({"command": "echo hi"}, ctx)

    assert captured["kwargs"]["stdin"] is sp.DEVNULL
    env = captured["kwargs"]["env"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["DEBIAN_FRONTEND"] == "noninteractive"
    assert "exit_code: 0" in out
