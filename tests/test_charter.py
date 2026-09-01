"""项目宪章（Coding-Agent.md）：读取 / 追加 / 注入系统提示 测试。

验证点：
  1. load_charter：文件不存在返回空、存在返回全文。
  2. charter 工具：action=read 读全文、action=add 创建/追加不覆盖。
  3. 边界：add 空 content 报错、未知 action 报错。
  4. build_system_prompt 能把宪章注入系统提示。
  5. charter 工具已注册进默认工具注册表。
"""
from __future__ import annotations

import pytest

from coding_agent.agent import SYSTEM_PROMPT, build_system_prompt
from coding_agent.charter import load_charter
from coding_agent.errors import ToolError
from coding_agent.tools.charter import CHARTER
from coding_agent.tools.registry import ToolContext


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(workdir=tmp_path)


def charter_file(ctx):
    return ctx.workdir / "Coding-Agent.md"


# --------------------------------------------------------------------------- #
# load_charter
# --------------------------------------------------------------------------- #


def test_load_charter_missing_returns_empty(ctx):
    assert load_charter(ctx.workdir) == ("", False)


def test_load_charter_returns_full_text(ctx):
    charter_file(ctx).write_text("第一条规则\n第二条规则\n", encoding="utf-8")
    text, has = load_charter(ctx.workdir)
    assert has is True
    assert text == "第一条规则\n第二条规则\n"


# --------------------------------------------------------------------------- #
# charter 工具：read
# --------------------------------------------------------------------------- #


def test_read_missing_charter_returns_hint(ctx):
    result = CHARTER.handler({"action": "read"}, ctx)
    assert "没有宪章" in result
    assert "Coding-Agent.md" in result


def test_read_existing_charter(ctx):
    charter_file(ctx).write_text("永远不要改 tests/\n", encoding="utf-8")
    result = CHARTER.handler({"action": "read"}, ctx)
    assert "永远不要改 tests/" in result
    assert "Coding-Agent.md" in result


# --------------------------------------------------------------------------- #
# charter 工具：add（创建 / 追加）
# --------------------------------------------------------------------------- #


def test_add_creates_file(ctx):
    ctx.confirm = lambda _: True  # 确认放行
    result = CHARTER.handler(
        {"action": "add", "content": "永远不要修改 spec/ 目录"}, ctx
    )
    assert "创建" in result
    text = charter_file(ctx).read_text(encoding="utf-8")
    assert "永远不要修改 spec/ 目录" in text


def test_add_appends_without_overwriting(ctx):
    ctx.confirm = lambda _: True
    charter_file(ctx).write_text("旧规则\n", encoding="utf-8")
    CHARTER.handler({"action": "add", "content": "新规则"}, ctx)
    text = charter_file(ctx).read_text(encoding="utf-8")
    assert "旧规则" in text  # 原有内容保留
    assert "新规则" in text  # 新条款追加


def test_add_multiple_times_all_kept(ctx):
    ctx.confirm = lambda _: True
    CHARTER.handler({"action": "add", "content": "规则A"}, ctx)
    CHARTER.handler({"action": "add", "content": "规则B"}, ctx)
    text = charter_file(ctx).read_text(encoding="utf-8")
    assert "规则A" in text
    assert "规则B" in text


def test_add_empty_content_raises(ctx):
    with pytest.raises(ToolError):
        CHARTER.handler({"action": "add", "content": "   "}, ctx)
    assert not charter_file(ctx).exists()


# --------------------------------------------------------------------------- #
# charter 工具：add 确认门控（跨会话持久写默认拒绝）
# --------------------------------------------------------------------------- #


def test_add_denied_when_no_confirm_callback(ctx):
    # 无 confirm 回调（非交互）→ 默认拒绝，且不落盘
    with pytest.raises(ToolError, match="确认"):
        CHARTER.handler({"action": "add", "content": "规则"}, ctx)
    assert not charter_file(ctx).exists()


def test_add_denied_when_user_declines(ctx):
    ctx.confirm = lambda _: False  # 用户拒绝
    with pytest.raises(ToolError, match="取消"):
        CHARTER.handler({"action": "add", "content": "规则"}, ctx)
    assert not charter_file(ctx).exists()


def test_add_allowed_with_auto_approve(ctx):
    ctx.auto_approve = True  # --auto-approve 绕过确认
    result = CHARTER.handler({"action": "add", "content": "规则"}, ctx)
    assert "创建" in result
    assert charter_file(ctx).exists()


# --------------------------------------------------------------------------- #
# charter 工具：未知 action
# --------------------------------------------------------------------------- #


def test_unknown_action_raises(ctx):
    with pytest.raises(ToolError, match="未知 action"):
        CHARTER.handler({"action": "delete"}, ctx)


# --------------------------------------------------------------------------- #
# build_system_prompt 宪章注入
# --------------------------------------------------------------------------- #


def test_build_system_prompt_injects_charter():
    prompt = build_system_prompt(charter_text="约束：不得使用 write_file 写 secrets/")
    assert prompt.startswith(SYSTEM_PROMPT)
    assert "不得使用 write_file 写 secrets/" in prompt
    assert "项目宪章" in prompt


def test_build_system_prompt_empty_charter_not_injected():
    assert build_system_prompt() == SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# 注册表
# --------------------------------------------------------------------------- #


def test_charter_registered_in_default_registry():
    from coding_agent.tools import build_default_registry

    reg = build_default_registry()
    assert "charter" in reg.names()
