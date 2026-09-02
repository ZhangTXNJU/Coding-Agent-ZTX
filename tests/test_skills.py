"""skill 系统测试：内置 skill / 自定义解析 / 注册 / use_skill 工具 / 系统提示。"""
from __future__ import annotations

import pytest

from coding_agent.agent import SYSTEM_PROMPT, build_system_prompt
from coding_agent.errors import ToolError
from coding_agent.skills import (
    BUILTIN_SKILLS,
    Skill,
    SkillRegistry,
    build_skill_registry,
    build_skills_prompt,
    load_custom_skills,
    parse_skill_file,
    skill_prompt,
)
from coding_agent.tools import USE_SKILL, ToolContext, build_default_registry

BUILTIN_NAMES = {"code-review", "write-tests", "refactor", "write-docs", "explain-code"}


def _write_skill(tmp_path, content: str, filename: str = "my-skill.md"):
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


VALID = (
    "---\n"
    "name: my-skill\n"
    "description: 我的自定义技能\n"
    "---\n"
    "第一步：读代码。\n第二步：总结。\n"
)


# --------------------------------------------------------------------------- #
# 内置 skill
# --------------------------------------------------------------------------- #


def test_builtin_skills_cover_five_scenarios():
    names = {s.name for s in BUILTIN_SKILLS}
    assert BUILTIN_NAMES <= names
    assert len(BUILTIN_SKILLS) >= 5


def test_builtin_create_skill_present():
    skill = next(s for s in BUILTIN_SKILLS if s.name == "create-skill")
    assert skill.description
    # 指引须引导把 skill 写到约定目录
    assert "~/.coding-agent/skills" in skill.instructions


def test_builtin_skill_has_required_fields():
    for s in BUILTIN_SKILLS:
        assert s.name
        assert s.description
        assert s.instructions
        assert s.source == "builtin"


def test_build_skill_registry_has_builtins():
    reg, errors, warnings = build_skill_registry()
    assert errors == [] and warnings == []
    assert BUILTIN_NAMES <= set(reg.names())


# --------------------------------------------------------------------------- #
# 自定义 skill 解析
# --------------------------------------------------------------------------- #


def test_parse_skill_file_valid(tmp_path):
    skill = parse_skill_file(_write_skill(tmp_path, VALID))
    assert isinstance(skill, Skill)
    assert skill.name == "my-skill"
    assert skill.description == "我的自定义技能"
    assert "读代码" in skill.instructions
    assert skill.source == "custom"


def test_parse_skill_file_missing_name(tmp_path):
    msg = parse_skill_file(
        _write_skill(tmp_path, "---\ndescription: x\n---\n正文\n", "a.md")
    )
    assert isinstance(msg, str)
    assert "name" in msg


def test_parse_skill_file_missing_description(tmp_path):
    msg = parse_skill_file(_write_skill(tmp_path, "---\nname: x\n---\n正文\n", "a.md"))
    assert isinstance(msg, str)
    assert "description" in msg


def test_parse_skill_file_empty_body(tmp_path):
    msg = parse_skill_file(
        _write_skill(tmp_path, "---\nname: x\ndescription: y\n---\n", "a.md")
    )
    assert isinstance(msg, str)
    assert "执行指引" in msg


def test_parse_skill_file_invalid_name(tmp_path):
    msg = parse_skill_file(
        _write_skill(tmp_path, "---\nname: Bad Name!\ndescription: y\n---\n正文\n", "a.md")
    )
    assert isinstance(msg, str)
    assert "name" in msg


def test_load_custom_skills_mixed(tmp_path):
    _write_skill(tmp_path, VALID, "good.md")
    _write_skill(tmp_path, "---\ndescription: 缺 name\n---\n正文\n", "bad.md")
    skills, errors = load_custom_skills(tmp_path)
    assert [s.name for s in skills] == ["my-skill"]
    assert len(errors) == 1
    assert "bad.md" in errors[0]


def test_load_custom_skills_missing_dir(tmp_path):
    skills, errors = load_custom_skills(tmp_path / "nonexistent")
    assert skills == [] and errors == []


def test_custom_overrides_builtin(tmp_path):
    _write_skill(
        tmp_path,
        "---\nname: code-review\ndescription: 我的审查\n---\n自定义指引\n",
    )
    reg, errors, warnings = build_skill_registry(custom_dir=tmp_path)
    assert errors == []
    assert len(warnings) == 1
    assert "覆盖" in warnings[0]
    assert reg.get("code-review").description == "我的审查"
    assert reg.get("code-review").source == "custom"


# --------------------------------------------------------------------------- #
# use_skill 工具
# --------------------------------------------------------------------------- #


def test_use_skill_returns_instructions(tmp_path):
    reg, _, _ = build_skill_registry()
    ctx = ToolContext(workdir=tmp_path, skills=reg)
    out = USE_SKILL.handler({"name": "code-review"}, ctx)
    assert "【skill: code-review】" in out
    assert "审查" in out


def test_use_skill_unknown_lists_available(tmp_path):
    reg, _, _ = build_skill_registry()
    ctx = ToolContext(workdir=tmp_path, skills=reg)
    with pytest.raises(ToolError, match="不存在"):
        USE_SKILL.handler({"name": "nope"}, ctx)


def test_use_skill_registered_in_default_registry():
    names = set(build_default_registry().names())
    assert "use_skill" in names


def test_skill_prompt_renders_instructions():
    skill = Skill("code-review", "审查代码质量", "第一步：审查。", "builtin")
    out = skill_prompt(skill)
    assert "【skill: code-review】" in out
    assert "审查代码质量" in out
    assert "第一步：审查。" in out


# --------------------------------------------------------------------------- #
# 系统提示注入
# --------------------------------------------------------------------------- #


def test_build_system_prompt_lists_skills():
    reg, _, _ = build_skill_registry()
    prompt = build_system_prompt(reg)
    assert prompt.startswith(SYSTEM_PROMPT)
    for name in BUILTIN_NAMES:
        assert name in prompt


def test_build_system_prompt_empty_registry_falls_back():
    assert build_system_prompt(SkillRegistry()) == SYSTEM_PROMPT


def test_system_prompt_guides_background_for_servers():
    # 系统提示须引导模型：永不退出的命令（server/守护/REPL）走 background，避免同步阻塞
    assert "background=true" in SYSTEM_PROMPT
    for keyword in ("服务器", "守护进程", "REPL"):
        assert keyword in SYSTEM_PROMPT


def test_build_skills_prompt_empty():
    assert build_skills_prompt(SkillRegistry()) == ""


# --------------------------------------------------------------------------- #
# 只读 skill（read_only 字段）
# --------------------------------------------------------------------------- #


def test_read_only_defaults_false():
    assert Skill("x", "desc", "instr").read_only is False


def test_parse_skill_file_read_only_true(tmp_path):
    content = "---\nname: my-plan\ndescription: 只读规划\nread_only: true\n---\n正文\n"
    skill = parse_skill_file(_write_skill(tmp_path, content))
    assert isinstance(skill, Skill)
    assert skill.read_only is True


def test_parse_skill_file_read_only_defaults_false(tmp_path):
    skill = parse_skill_file(_write_skill(tmp_path, VALID))
    assert isinstance(skill, Skill)
    assert skill.read_only is False


def test_builtin_phase_skills_read_only_flags():
    reg, _, _ = build_skill_registry()
    for name in ("specify", "clarify", "plan", "tasks"):
        assert reg.get(name).read_only is True
    assert reg.get("implement").read_only is False


def test_build_skills_prompt_marks_read_only():
    reg, _, _ = build_skill_registry()
    assert "（只读）" in build_skills_prompt(reg)
