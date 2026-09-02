"""后台任务测试：bash background=true + background_wait/status/cancel/list + 推送收集。

用真实 shell 命令（echo / sleep）验证「后台启动 → 查询/状态/取消/列表」的完整闭环；
注册表为模块级全局，测试间用 autouse fixture 隔离重置，避免 task_id 序号串扰。
"""
from __future__ import annotations

import time

import pytest

from coding_agent.errors import ToolError
from coding_agent.tools import (
    BASH,
    BACKGROUND_CANCEL,
    BACKGROUND_LIST,
    BACKGROUND_STATUS,
    BACKGROUND_WAIT,
    build_default_registry,
)
from coding_agent.tools.bash import cleanup_background_tasks, collect_finished_background_tasks
from coding_agent.tools.registry import ToolContext


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(workdir=tmp_path)


@pytest.fixture(autouse=True)
def _reset_background():
    """隔离模块级后台任务注册表：每个测试前清空，测试后杀进程并删临时文件。"""
    import coding_agent.tools.bash as bash_mod

    bash_mod._BG_TASKS.clear()
    bash_mod._BG_SEQ = 0
    yield
    cleanup_background_tasks()


# --------------------------------------------------------------------------- #
# 后台启动 → 等待 完整闭环
# --------------------------------------------------------------------------- #


def test_background_bash_then_wait_returns_output(ctx):
    out = BASH.handler({"command": "echo hello", "background": True}, ctx)
    assert "已后台启动任务 #1" in out

    result = BACKGROUND_WAIT.handler({"task_id": "1"}, ctx)
    assert "exit_code: 0" in result
    assert "hello" in result


def test_background_bash_still_running_then_done(ctx):
    BASH.handler({"command": "sleep 1; echo done", "background": True}, ctx)

    running = BACKGROUND_WAIT.handler({"task_id": "1", "timeout": 0.1}, ctx)
    assert "仍在运行" in running

    done = BACKGROUND_WAIT.handler({"task_id": "1", "timeout": 10}, ctx)
    assert "exit_code: 0" in done
    assert "done" in done


def test_background_bash_wait_cleans_up(ctx):
    BASH.handler({"command": "echo x", "background": True}, ctx)
    BACKGROUND_WAIT.handler({"task_id": "1"}, ctx)
    with pytest.raises(ToolError):
        BACKGROUND_WAIT.handler({"task_id": "1"}, ctx)


def test_background_bash_unknown_task_raises(ctx):
    with pytest.raises(ToolError, match="未知"):
        BACKGROUND_WAIT.handler({"task_id": "999"}, ctx)


def test_background_bash_dangerous_denied(ctx):
    with pytest.raises(ToolError):
        BASH.handler({"command": "rm -rf /tmp/x", "background": True}, ctx)


def test_background_bash_task_ids_increment(ctx):
    out1 = BASH.handler({"command": "echo a", "background": True}, ctx)
    out2 = BASH.handler({"command": "echo b", "background": True}, ctx)
    out3 = BASH.handler({"command": "echo c", "background": True}, ctx)
    assert "任务 #1" in out1
    assert "任务 #2" in out2
    assert "任务 #3" in out3


# --------------------------------------------------------------------------- #
# 状态 / 取消 / 列表
# --------------------------------------------------------------------------- #


def test_background_status_running(ctx):
    BASH.handler({"command": "sleep 1", "background": True}, ctx)
    assert "仍在运行" in BACKGROUND_STATUS.handler({"task_id": "1"}, ctx)


def test_background_status_done_returns_output(ctx):
    BASH.handler({"command": "echo hi", "background": True}, ctx)
    time.sleep(0.2)  # 给 echo 足够时间结束
    out = BACKGROUND_STATUS.handler({"task_id": "1"}, ctx)
    assert "exit_code: 0" in out
    assert "hi" in out


def test_background_cancel_kills_task(ctx):
    BASH.handler({"command": "sleep 30", "background": True}, ctx)
    assert "已取消" in BACKGROUND_CANCEL.handler({"task_id": "1"}, ctx)
    with pytest.raises(ToolError):
        BACKGROUND_WAIT.handler({"task_id": "1"}, ctx)


def test_background_cancel_unknown_raises(ctx):
    with pytest.raises(ToolError, match="未知"):
        BACKGROUND_CANCEL.handler({"task_id": "999"}, ctx)


def test_background_list_empty(ctx):
    assert "没有" in BACKGROUND_LIST.handler({}, ctx)


def test_background_list_shows_running(ctx):
    BASH.handler({"command": "sleep 30", "background": True}, ctx)
    out = BACKGROUND_LIST.handler({}, ctx)
    assert "#1" in out
    assert "运行中" in out
    BACKGROUND_CANCEL.handler({"task_id": "1"}, ctx)


# --------------------------------------------------------------------------- #
# 推送收集 / 注册 / 清理
# --------------------------------------------------------------------------- #


def test_collect_finished_background_tasks(ctx):
    BASH.handler({"command": "echo collected", "background": True}, ctx)
    time.sleep(0.2)
    results = collect_finished_background_tasks()
    assert len(results) == 1
    tid, code, output = results[0]
    assert tid == "1"
    assert code == 0
    assert "collected" in output
    # 收集后任务从注册表移除
    with pytest.raises(ToolError):
        BACKGROUND_WAIT.handler({"task_id": "1"}, ctx)


def test_background_tools_registered_in_default_registry():
    reg = build_default_registry()
    for name in ("background_wait", "background_status", "background_cancel", "background_list"):
        assert name in reg.names()


def test_cleanup_background_tasks_kills_running(ctx):
    BASH.handler({"command": "sleep 5", "background": True}, ctx)
    cleanup_background_tasks()
    with pytest.raises(ToolError, match="未知"):
        BACKGROUND_WAIT.handler({"task_id": "1"}, ctx)
