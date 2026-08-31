"""skill 系统：内置 + 自定义 skill 的定义、加载与注册。

一个 Skill = 名称 + 用途说明 + 执行指引。触发后把「执行指引」注入上下文，
引导模型按约定流程产出格式一致的结果（仿 Claude Code / OpenCode 的 skill）。

自定义 skill 采用单个 markdown 描述文件，约定格式（frontmatter + 正文）：

    ---
    name: my-skill
    description: 一句话说明这个 skill 做什么、何时用
    ---
    （正文即执行指引）

文件放入约定目录（默认 ~/.coding-agent/skills/）即被启动时发现。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# 约定目录：与 ~/.coding-agent/sessions/ 同级，存放用户自定义 skill
DEFAULT_SKILLS_DIR = Path.home() / ".coding-agent" / "skills"

# 合法 skill 名：小写字母/数字/连字符（至少一个字符，不能以连字符开头）
_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


@dataclass
class Skill:
    """一个可复用的能力单元。"""

    name: str
    description: str  # 用途说明：让模型判断「何时适用」
    instructions: str  # 执行指引：触发后注入上下文的正文
    source: str = "builtin"  # "builtin" | "custom"


class SkillRegistry:
    """name → Skill 的注册表（保持插入顺序：内置在前，自定义在后）。"""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def names(self) -> list[str]:
        return list(self._skills)

    def list(self) -> list[Skill]:
        return list(self._skills.values())

    def __contains__(self, name: str) -> bool:
        return name in self._skills

    def __len__(self) -> int:
        return len(self._skills)

    def __bool__(self) -> bool:
        return bool(self._skills)


# --------------------------------------------------------------------------- #
# 内置 skill：覆盖 ≥5 个常见编程场景
# --------------------------------------------------------------------------- #

BUILTIN_SKILLS = [
    Skill(
        name="code-review",
        description="对代码改动进行系统审查，产出分级问题清单与改进建议",
        instructions=(
            "对目标代码进行系统审查，按以下流程执行：\n\n"
            "1. 先定位待审查的改动或文件（用 bash 跑 git diff、grep 或 read_file 了解范围）。\n"
            "2. 逐项检查：\n"
            "   - 正确性：逻辑错误、边界条件、空值/异常处理\n"
            "   - 安全：注入、越权、敏感信息泄露、路径穿越\n"
            "   - 性能：不必要的重复计算、大循环、阻塞调用\n"
            "   - 可维护性：命名、重复代码、过长函数、缺失注释\n"
            "3. 按严重程度分级输出审查报告：\n"
            "   - 🔴 严重（bug / 安全，必须修）\n"
            "   - 🟡 建议（可维护性 / 性能，值得改）\n"
            "   - 🟢 优化（锦上添花）\n"
            "   每条给出：问题位置（文件:行号）、问题描述、修复建议。\n"
            "4. 结尾给出总体评价（一句话 + 是否建议合入）。"
        ),
    ),
    Skill(
        name="write-tests",
        description="为目标代码生成测试，覆盖正常/边界/异常路径并验证通过",
        instructions=(
            "为目标代码生成测试，按以下流程执行：\n\n"
            "1. 先 read_file 阅读目标代码，弄清公开接口、输入输出、边界条件。\n"
            "2. 识别项目现有测试框架与目录约定（找 tests/ 或 *_test.*）。\n"
            "3. 为每个关键行为编写测试用例，覆盖：\n"
            "   - 正常路径（happy path）\n"
            "   - 边界条件（空输入、极值、越界）\n"
            "   - 异常路径（非法输入、缺失依赖、失败分支）\n"
            "4. 断言必须具体（断言确切输出 / 状态），不要只断言「不抛异常」。\n"
            "5. 用 bash 运行测试命令，确认全部通过；失败则修复测试或代码。\n"
            "6. 回报：新增/修改了哪些测试文件、覆盖了哪些场景、运行结果。"
        ),
    ),
    Skill(
        name="refactor",
        description="对目标代码做行为不变的等价重构，每步改动后验证",
        instructions=(
            "对目标代码进行安全重构，按以下流程执行：\n\n"
            "1. 先理解现状：read_file 阅读目标文件，用 grep 列出依赖它的调用点。\n"
            "2. 明确重构目标：消除重复、拆分长函数、改善命名、提取常量/配置、理顺依赖。\n"
            "3. 遵循「小步走、行为不变」原则：每次只做一处等价变换。\n"
            "4. 每次改动后立即用 bash 跑测试或类型检查，确认行为未变。\n"
            "5. 若无测试，先补一个最小验证（运行关键路径）。\n"
            "6. 回报：重构了哪些点、为什么、如何验证行为未变（附测试/运行结果）。"
        ),
    ),
    Skill(
        name="write-docs",
        description="为目标代码编写 README / docstring / API 文档",
        instructions=(
            "为目标代码编写文档，按以下流程执行：\n\n"
            "1. read_file 阅读目标代码，弄清用途、公开接口、依赖、用法。\n"
            "2. 根据对象选择合适的文档形态：\n"
            "   - README：项目用途、快速开始、目录结构、示例\n"
            "   - 模块/函数 docstring：一句话用途 + 参数 + 返回 + 异常\n"
            "   - API 文档：端点/签名/字段说明\n"
            "3. 文档要点：\n"
            "   - 面向「第一次接触的人」，先讲是什么、为什么，再讲怎么用\n"
            "   - 提供可运行的示例（代码块）\n"
            "   - 标注关键注意事项 / 陷阱\n"
            "4. 用 write_file / edit_file 写入文档，语言简洁准确。\n"
            "5. 回报：写了哪些文档、放在哪里、覆盖了什么。"
        ),
    ),
    Skill(
        name="explain-code",
        description="用由整体到局部的方式讲解目标代码",
        instructions=(
            "为目标代码给出清晰解释，按以下流程执行：\n\n"
            "1. read_file 阅读目标代码（必要时 grep 追踪调用关系）。\n"
            "2. 按「从整体到局部」组织解释：\n"
            "   - 这段代码是做什么的（一句话）\n"
            "   - 整体结构 / 数据流（关键模块与它们的关系）\n"
            "   - 关键函数 / 逻辑逐段讲解（贴关键代码 + 说明）\n"
            "   - 易错点 / 注意点\n"
            "3. 面向对象：默认假设读者已懂编程但没读过这份代码；如读者是初学者再降难度。\n"
            "4. 解释要具体到代码，避免空泛的套话。"
        ),
    ),
]


# --------------------------------------------------------------------------- #
# 自定义 skill 解析
# --------------------------------------------------------------------------- #


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析首部 `--- ... ---` frontmatter，返回 (字段 dict, 正文)。

    无 frontmatter 或未闭合时返回 ({}, 原文)。
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip().lower()] = value.strip().strip("\"'")
    body = "\n".join(lines[end + 1 :]).strip()
    return fields, body


def parse_skill_file(path: Path) -> Skill | str:
    """解析单个 skill 文件。返回 Skill；非法时返回错误信息字符串。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"{path.name}: 无法读取（{exc}）"

    fields, body = _parse_frontmatter(text)
    name = fields.get("name", "").strip()
    description = fields.get("description", "").strip()

    if not name:
        return f"{path.name}: 缺少 name 字段"
    if not _NAME_RE.fullmatch(name):
        return f"{path.name}: 非法 name（{name!r}），需为小写字母/数字/连字符"
    if not description:
        return f"{path.name}: 缺少 description 字段"
    if not body:
        return f"{path.name}: 缺少执行指引（正文为空）"
    return Skill(name=name, description=description, instructions=body, source="custom")


def load_custom_skills(directory: Path) -> tuple[list[Skill], list[str]]:
    """扫描目录下 *.md 文件，返回 (合法 skills, 错误信息列表)。

    目录不存在视为「没有自定义 skill」，不报错。
    """
    skills: list[Skill] = []
    errors: list[str] = []
    if not directory.is_dir():
        return skills, errors
    for path in sorted(directory.glob("*.md")):
        result = parse_skill_file(path)
        if isinstance(result, Skill):
            skills.append(result)
        else:
            errors.append(result)
    return skills, errors


def build_skill_registry(
    custom_dir: Path | None = None,
) -> tuple[SkillRegistry, list[str], list[str]]:
    """构建完整注册表：内置 + 自定义。返回 (registry, errors, warnings)。

    - 同名时自定义覆盖内置（记录 warning）。
    - 非法自定义文件单独记录 error，不影响其它 skill。
    """
    registry = SkillRegistry()
    for skill in BUILTIN_SKILLS:
        registry.register(skill)

    errors: list[str] = []
    warnings: list[str] = []
    if custom_dir is not None:
        customs, errors = load_custom_skills(custom_dir)
        for skill in customs:
            if skill.name in registry:
                warnings.append(f"自定义 skill「{skill.name}」覆盖同名内置 skill")
            registry.register(skill)
    return registry, errors, warnings


def build_skills_prompt(registry: SkillRegistry) -> str:
    """生成追加到系统提示的 skill 列表（供模型判断何时使用 use_skill）。"""
    if not registry:
        return ""
    entries = "\n".join(f"- {s.name}：{s.description}" for s in registry.list())
    return "可用 skill（任务匹配时先用 use_skill 加载其指引再执行）：\n" + entries
