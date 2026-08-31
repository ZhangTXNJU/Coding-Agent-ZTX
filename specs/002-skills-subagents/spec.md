# Feature Specification: Skill 与 Subagent（能力扩展）

**Feature Branch**: `004-skills-subagents`

**Created**: 2026-08-31

**Status**: Draft

**Input**: User description: "我希望在当前项目基础上继续开发更强的coding agent功能：1.skill（实现一些常用skill并支持自定义自行创建skill的功能），2.subagent实现子agent调用。把上述的两个需求提上日程吧。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 调用内置常用 skill (Priority: P1)

开发者对 agent 说一句自然语言（或显式指定 skill 名），agent 识别并加载对应的内置 skill（如"代码审查""生成测试""重构""编写文档""解释代码"），按该 skill 预设的流程执行，产出格式统一、质量一致的结果。

**Why this priority**: skill 是"把专家经验固化成可复用流程"的核心价值，让 agent 在常见任务上产出更稳定可靠，是本次扩展最直接、可演示的能力。

**Independent Test**: 对一个示例仓库依次触发 2–3 个内置 skill，观察每个 skill 是否按其约定的步骤执行并产出结构化结果，全程无需人工干预。

**Acceptance Scenarios**:

1. **Given** 仓库中存在可审查的代码，**When** 用户要求"用代码审查 skill 检查这段改动"，**Then** agent 按审查流程产出包含问题分级与建议的审查报告。
2. **Given** 用户用显式名称触发某个 skill，**When** 该 skill 存在，**Then** agent 加载其指令并执行，产出与该 skill 约定一致的结果。
3. **Given** 用户用自然语言描述了与某 skill 匹配的需求，**When** agent 判断该 skill 适用，**Then** agent 自动选用该 skill 而不是走通用流程。

---

### User Story 2 - 创建并使用自定义 skill (Priority: P1)

开发者编写一个简单的 skill 描述（含名称、用途说明、执行指引），将其放入约定位置后，agent 即可像内置 skill 一样识别并调用它。

**Why this priority**: 自定义是 skill 能力的另一半——让用户把个人或团队的专属经验沉淀为可复用能力，是"常用 skill"之外的关键增量。

**Independent Test**: 用户新建一个自定义 skill 描述文件，刷新后，验证该 skill 出现在可用列表并可被正常触发执行。

**Acceptance Scenarios**:

1. **Given** 用户写了一个合法的自定义 skill 描述文件，**When** agent 刷新或启动后，**Then** 该 skill 出现在可用 skill 列表中。
2. **Given** 一个已注册的自定义 skill，**When** 用户触发它，**Then** agent 按其自定义指引执行。
3. **Given** 描述文件缺少必要字段或格式非法，**When** agent 加载它，**Then** agent 拒绝加载并提示具体缺失或错误位置，而不影响其它 skill。

---

### User Story 3 - 委托子任务给 subagent (Priority: P1)

面对一个包含多块相对独立工作的任务，agent 把其中一块交给一个子 agent 独立完成；子 agent 在自己有限的步数内工作，结束后把结论或成果回报给主 agent，主 agent 整合后继续完成整体任务。

**Why this priority**: subagent 是"分而治之"的关键——让主 agent 保持对全局的把控，同时把机械、独立、易膨胀的子工作隔离出去，直接提升处理复杂任务的能力与上下文效率。

**Independent Test**: 下达一个可自然拆分的复合任务，观察 agent 是否把某块工作委托给子 agent、子 agent 独立产出并回报、主 agent 正确整合。

**Acceptance Scenarios**:

1. **Given** 一个可拆分的复合任务，**When** 主 agent 判断存在独立子任务，**Then** 它把子任务委托给子 agent 执行。
2. **Given** 子 agent 完成了子任务，**When** 它结束，**Then** 其结果以结构化摘要回报主 agent。
3. **Given** 子 agent 执行失败或产出为空，**When** 它结束，**Then** 主 agent 收到失败或空结果信号并能据此决定重试或调整，而非静默当作成功。

---

### User Story 4 - subagent 上下文隔离 (Priority: P2)

子 agent 的完整工作过程（大量工具调用与中间输出）只存在于子 agent 自己的上下文中，回报给主 agent 的仅是最终结论；主对话因此不被中间过程撑大，仍能容纳整体任务。

**Why this priority**: 上下文隔离是 subagent 区别于"直接在主流程里多跑几步"的本质价值，决定了它能否真正解决长任务上下文膨胀的问题。

**Independent Test**: 用一个会产生大量中间输出的子任务，对比"委托子 agent"与"主流程直接做"两种情况下主对话的消息量，验证委托后主上下文明显更小且任务仍完成。

**Acceptance Scenarios**:

1. **Given** 子 agent 在执行中产生大量中间步骤，**When** 其完成后回报，**Then** 主对话只新增最终结论，不含中间过程。
2. **Given** 主 agent 连续委托多个子 agent，**When** 全部完成，**Then** 主上下文仍保持在可承受范围内，未达模型上限。

---

### User Story 5 - 查看可用 skill (Priority: P2)

开发者通过一个命令查看当前所有可用 skill（内置 + 自定义），了解每个 skill 的名称与用途，便于选用。

**Why this priority**: 可发现性是 skill 能被实际使用的前提；没有列表，用户不知道有哪些能力可用。

**Independent Test**: 在含内置与自定义 skill 的环境里执行列表命令，验证所有 skill 均按名称加用途展示。

**Acceptance Scenarios**:

1. **Given** 环境里存在内置与自定义 skill，**When** 用户执行查看命令，**Then** 列表展示全部 skill 及各自用途。
2. **Given** 没有任何自定义 skill，**When** 用户查看，**Then** 仍能看到内置 skill 列表。

---

### User Story 6 - 异常与安全边界 (Priority: P3)

skill 与 subagent 在遇到异常（skill 不存在、名称冲突、子 agent 越权或失控）时，给出清晰反馈并守住安全边界（破坏性命令仍需确认），绝不静默失败或绕过权限。

**Why this priority**: 这是健壮性与安全合规的兜底，保证新能力不破坏 agent 已有的权限模型与可靠性。

**Independent Test**: 构造"不存在的 skill 名""重名 skill""子 agent 尝试破坏性命令""子 agent 超步数"等场景，逐一验证系统反馈清晰且权限边界不被绕过。

**Acceptance Scenarios**:

1. **Given** 用户触发一个不存在的 skill，**When** 该名称无效，**Then** agent 明确提示不存在并列出相近或可用 skill，而非崩溃。
2. **Given** 自定义 skill 与内置 skill 重名，**When** 加载时，**Then** 按既定优先级处理（如自定义覆盖内置）并提示用户。
3. **Given** 子 agent 尝试执行破坏性命令，**When** 该命令需要确认，**Then** 沿用主 agent 的权限确认机制，不允许绕过。
4. **Given** 子 agent 达到步数或时间上限仍未完成，**When** 触发上限，**Then** 子 agent 停止并把"未完成"状态回报主 agent。

---

### Edge Cases

- 触发一个不存在的 skill 名称：给出清晰报错与相近建议。
- 自定义 skill 定义非法（缺字段或格式错）：拒绝加载该 skill，提示具体问题，不影响其余。
- 自定义与内置重名：明确优先级并提示。
- skill 指引与用户当前明确指令冲突：以用户最新明确指令为准。
- 子 agent 内部失败、超时或超步数：回报失败状态，主 agent 决定重试或调整。
- 子 agent 产出为空：主 agent 感知并处理，不静默成功。
- 子 agent 越权执行危险命令：继承权限确认，禁止绕过。
- 子 agent 内再嵌套子 agent：v1 禁止或设嵌套深度上限。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 提供一组内置常用 skill，覆盖至少 5 个常见编程场景（如代码审查、生成测试、重构、编写文档、解释代码）。
- **FR-002**: 每个内置 skill MUST 包含名称、用途说明与执行指引，使 agent 能按该指引产出格式一致的结果。
- **FR-003**: 用户 MUST 能通过显式名称或自然语言触发一个 skill。
- **FR-004**: 用户 MUST 能通过编写一个描述文件（含名称、用途、指引）创建自定义 skill。
- **FR-005**: 系统 MUST 在启动或刷新时发现并加载合法自定义 skill，使其与内置 skill 同等可被触发。
- **FR-006**: 系统 MUST 对非法或缺失字段的自定义 skill 定义给出具体错误提示并拒绝加载，且不影响其它 skill。
- **FR-007**: 用户 MUST 能通过一个命令查看全部可用 skill（内置 + 自定义）及各自用途。
- **FR-008**: 系统 MUST 支持主 agent 将独立子任务委托给一个子 agent 独立执行。
- **FR-009**: 子 agent MUST 在独立上下文中工作，只把最终结论回报主 agent，中间过程不进入主对话。
- **FR-010**: 子 agent MUST 具备独立的步数或时间上限，达到上限即停止并回报"未完成"状态。
- **FR-011**: 子 agent 完成或失败后 MUST 向主 agent 回报结构化结果（成功则含成果，失败则含原因）。
- **FR-012**: 系统 MUST 让子 agent 沿用主 agent 的权限确认边界（破坏性命令仍需确认），禁止绕过。
- **FR-013**: 系统 MUST 在 skill 不存在、名称冲突、子 agent 失败等异常时给出清晰反馈，绝不静默失败。
- **FR-014**: 系统 MUST 限制子 agent 的嵌套深度（v1 默认禁止子 agent 再委托子 agent）。

### Key Entities *(include if feature involves data)*

- **Skill（技能）**：一个可复用的能力单元，含名称、用途说明、执行指引、来源（内置或自定义）；同名时存在优先级规则。
- **Skill 定义（自定义）**：用户编写的描述文件，声明 skill 的名称、用途与指引，是自定义 skill 的载体。
- **Subagent 任务（子代理任务）**：一次委托，含指令、上下文与权限边界、步数与时间上限。
- **Subagent 结果（子代理结果）**：子 agent 结束后的结构化回报，含成功状态与成果或失败原因。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 用户能用一句自然语言或显式名称触发任意内置 skill，并在无人干预下得到符合该 skill 约定的产出（基于 3 个演示任务的触发成功率 ≥ 90%）。
- **SC-002**: 用户能在 5 分钟内编写一个自定义 skill 描述文件并成功触发它（从编写到可用）。
- **SC-003**: 内置 skill 覆盖至少 5 个常见编程场景。
- **SC-004**: 对可拆分的复合任务，agent 能委托子 agent 完成，且主对话的消息量相比"不委托直接做"减少 ≥ 50%。
- **SC-005**: 子 agent 失败、超时或产出为空时，100% 的场景下主 agent 收到失败或空信号并向用户给出可理解说明，不静默当作成功。
- **SC-006**: 全部新能力在遵守项目既有合规约束（不使用 agent 框架或 SDK，核心逻辑自写）的前提下实现。

## Assumptions

- 本次以"两个能力（skill + subagent）合并为一个特性"交付；如后续需要可拆分。
- "常用 skill" 的初始集合为代码审查、生成测试、重构、编写文档、解释代码等常见场景，具体清单在实现阶段细化。
- skill 的触发同时支持显式名称与自然语言语义匹配；显式触发为最优先、最可预测的方式。
- 自定义 skill 采用单个描述文件（markdown，含名称、用途、指引）作为载体，放入约定目录即被发现。
- 子 agent v1 为串行单层（不并行、不嵌套）；并行与嵌套作为后续增强。
- 子 agent 与主 agent 使用同一模型、同一套工具与权限模型，仅上下文与步数或时间上限独立。
- 本特性不引入任何 agent 框架或 SDK；skill 与 subagent 的加载、调度、上下文隔离、权限沿用均自写实现（沿用 requirement.md 硬性约束）。
