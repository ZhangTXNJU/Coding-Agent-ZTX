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
from dataclasses import dataclass
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
    read_only: bool = False  # True 时仅暴露只读工具（规划/需求阶段禁止修改代码）


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
    Skill(
        name="create-skill",
        description="创建或更新一个自定义 skill（把可复用流程固化成 skill 文件）",
        instructions=(
            "创建/更新一个自定义 skill，按以下流程执行：\n\n"
            "1. 确定 skill 名称：小写字母/数字/连字符，最好用「动词-名词」格式（如 fix-tests、create-skill），"
            "不能含空格或中文。\n"
            "2. 写用途说明（description）：一句话说明这个 skill 做什么、何时用，"
            "让 agent 在后续任务里能判断是否适用。\n"
            "3. 写执行指引（正文）：列出具体步骤，可参考内置 skill 的写法——先了解现状 → 分步执行 → 每步验证 → 回报结果。\n"
            "4. 把内容写成 markdown 文件，放到 ~/.coding-agent/skills/<name>.md，格式如下：\n\n"
            "   ---\n"
            "   name: <name>\n"
            "   description: <用途说明>\n"
            "   ---\n"
            "   （执行指引正文）\n\n"
            "5. 用 bash 确认文件已写入且格式正确：frontmatter 的 name/description 齐全、正文非空。\n"
            "6. 回报：创建了哪个 skill、放在哪里、用途是什么；并提醒用户新 skill 在下次启动后生效。\n\n"
            "注意：\n"
            "- name 必须唯一；与内置 skill 重名会覆盖内置（按需决定）。\n"
            "- 若用户想修改已有 skill，用 read_file 读取后 edit_file 更新对应文件。\n"
            "- 若该 skill 只做规划/分析、不应改动代码，可在 frontmatter 加一行 `read_only: true`，"
            "触发后会自动禁用写文件与 bash 工具。"
        ),
    ),
    # ------------------------------------------------------------------ #
    # 需求/计划阶段 skill（specify/clarify/plan/tasks 为只读，implement 落盘）
    # ------------------------------------------------------------------ #
    Skill(
        name="specify",
        description="把模糊的功能诉求澄清并固化为可执行的需求规格（只读，不改代码）",
        read_only=True,
        instructions=(
            "把一段功能诉求固化为可执行的需求规格，按以下流程执行：\n\n"
            "1. 先读清现状：用 read_file / list_dir / glob / grep 了解相关代码与项目结构，不要凭空假设。\n"
            "2. 拆解需求：识别目标用户、触发场景、期望行为、边界条件、约束。\n"
            "3. 对影响范围或存在多种合理解释的关键点，最多提 3 个 [NEEDS CLARIFICATION]（按 范围 > 安全 > 体验 > 技术细节 的优先级）。\n"
            "4. 输出结构化需求规格（Markdown）：\n"
            "   - 目标（用户价值，一段话）\n"
            "   - 用户场景与验收（可测试的验收条件）\n"
            "   - 功能需求（每条可验证，编号 FR-001...）\n"
            "   - 成功标准（可度量、与技术实现无关）\n"
            "   - 边界与非目标（明确不做什么）\n"
            "   - 假设与待澄清项\n"
            "5. 只输出规格文本，不写文件、不改代码。"
        ),
    ),
    Skill(
        name="clarify",
        description="针对已有需求规格提出澄清问题，把含糊处收敛为明确决策（只读）",
        read_only=True,
        instructions=(
            "针对需求规格做澄清，把含糊/矛盾/缺漏处收敛为明确决策，按以下流程执行：\n\n"
            "1. read_file 读取目标规格（若规格在近期对话中则直接引用），定位含糊、矛盾、缺漏之处。\n"
            "2. 逐条列出澄清问题，每条给出：上下文、需要确认什么、可选方案（A/B/C 及各自影响）。\n"
            "3. 按影响排序（范围 > 安全 > 体验 > 技术细节），一次最多 3 个问题；用 ask_user 工具"
            "把「问题 + 选项」抛给用户选择，等用户回答后据此更新规格。\n"
            "4. 输出更新后的规格要点，不写文件、不改代码。"
        ),
    ),
    Skill(
        name="plan",
        description="基于需求规格产出可执行的实现计划（只读，不改代码）",
        read_only=True,
        instructions=(
            "基于需求规格产出可执行的实现计划，按以下流程执行：\n\n"
            "1. 读清现状：read_file / list_dir / glob / grep 摸清相关代码、目录结构、现有模式与依赖。\n"
            "2. 设计实现方案：\n"
            "   - 技术方案与关键决策（选型、权衡）\n"
            "   - 架构/模块划分与数据流\n"
            "   - 涉及文件清单（新增/修改/删除，精确到路径）\n"
            "   - 分步实施顺序（含依赖关系）\n"
            "   - 风险与回滚点\n"
            "3. 输出实现计划（Markdown），步骤应能被 tasks skill 直接拆解为任务。\n"
            "4. 只输出计划文本，不写文件、不改代码。"
        ),
    ),
    Skill(
        name="tasks",
        description="把实现计划拆解为有序、带依赖与完成判据的任务清单（只读，只写 todo）",
        read_only=True,
        instructions=(
            "把实现计划拆解为有序、带依赖的任务清单，按以下流程执行：\n\n"
            "1. 输入为实现计划（近期对话中的 plan 输出或用户指定）。\n"
            "2. 拆成可独立完成的小任务，每条包含：内容、依赖、完成判据。\n"
            "3. 用 todo_write 把任务写入任务清单（每条 content 里写明完成判据），并按执行顺序排列依赖。\n"
            "4. 输出任务清单；本阶段只规划不实现，不写文件、不改代码。"
        ),
    ),
    Skill(
        name="implement",
        description="按既定的计划/任务清单执行实现，逐条完成并验证",
        read_only=False,
        instructions=(
            "按既定的计划/任务清单执行实现，按以下流程执行：\n\n"
            "1. 先读清现状与计划：read_file 读取计划/任务清单（或近期对话），确认范围与顺序。\n"
            "2. 用 todo_write 把任务清单设为进行中，逐条实施：\n"
            "   - 修改用 edit_file（精准替换），新建用 write_file，批量改动用 apply_patch\n"
            "   - 每完成一条，立即用 bash 跑测试/命令验证，再标记该 todo 完成\n"
            "3. 遵循计划，不擅自扩大范围；遇到计划外的关键决策先说明再动手。\n"
            "4. 全部完成后用 bash 回归验证，并一句话总结做了什么、如何验证。"
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
    read_only = fields.get("read_only", "").strip().lower() in ("true", "yes", "1", "on")
    return Skill(name=name, description=description, instructions=body, source="custom", read_only=read_only)


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
    entries = "\n".join(
        f"- {s.name}：{s.description}" + ("（只读）" if s.read_only else "")
        for s in registry.list()
    )
    return "可用 skill（任务匹配时先用 use_skill 加载其指引再执行）：\n" + entries


def skill_prompt(skill: Skill) -> str:
    """把 skill 渲染成注入上下文的指引文本（use_skill 工具与 /skill-name 调用共用）。"""
    return f"【skill: {skill.name}】{skill.description}\n\n{skill.instructions}"
