# Tasks: Coding Agent (编程智能体)

**Input**: Design documents from `specs/001-coding-agent/`（plan.md、spec.md、research.md、data-model.md、contracts/）

**Tests**: 本项目采用轻量测试（mock LLM 离线测循环 + 纯函数单测），用于在 3 天窗口内快速迭代而不消耗 API 额度。

**组织方式**: 按「构建依赖顺序」分阶段（自底向上），每阶段标注所属 user story。真正的 MVP 是 Phase 6（端到端闭环）。

## Phase 1: Setup（项目初始化）

**Purpose**: 项目骨架与依赖

- [x] T001 创建 `pyproject.toml`：包名 `coding_agent`、Python 3.11+、entry point `coding-agent = coding_agent.cli:main`
- [x] T002 在 `pyproject.toml` 声明依赖 `openai`/`rich`/`pydantic`/`python-dotenv` 与开发依赖 `pytest`
- [x] T003 [P] 创建 `coding_agent/__init__.py` 与 `coding_agent/__main__.py` 骨架（`python -m coding_agent` 可运行空入口）
- [x] T004 [P] 创建 `.env.example`（占位符 + provider 说明），确认 `.gitignore` 忽略 `.env`

---

## Phase 2: Foundational（阻塞性基础设施）

**Purpose**: 所有 user story 依赖的共享底座（配置 + 模型访问 + 错误处理）

**⚠️ CRITICAL**: 此阶段完成前不得开始任何 user story 实现

- [x] T005 实现 `coding_agent/config.py`：三级配置加载（命令行/env/.env/config.toml）+ `AgentConfig` 数据类（model/base_url/api_key_source/max_steps/max_failures/command_timeout/workdir/auto_approve）
- [x] T006 [P] 实现 `coding_agent/llm/providers.py`：端点注册表（deepseek/qwen/glm/kimi/minimax/custom → base_url + 默认模型）
- [x] T007 [P] 实现 `coding_agent/errors.py`：`AgentError`/`LLMError`/`ToolError` 类型 + 指数退避重试装饰器
- [x] T008 实现 `coding_agent/llm/client.py`：OpenAI 兼容流式 chat 封装，返回 `content` + `tool_calls`，集成重试（依赖 T006、T007）

**Checkpoint**: 底座就绪——`client.chat()` 能流式返回 DeepSeek 的文本与 tool_calls

---

## Phase 3: User Story 3 - 在本地安全地执行命令与读写文件 (Priority: P2)

**Goal**: 提供工具集（读/写/精准编辑/搜索/命令执行/任务清单），全部为可独立单测的纯函数

**Independent Test**: 不依赖 LLM，直接调用各工具函数验证：读文件返回内容、写文件落盘、edit 精准替换、bash 返回 stdout+退出码、危险命令被识别

### Implementation

- [x] T009 [US3] 实现 `coding_agent/tools/registry.py`：工具注册表（`name → (description, schema, handler)`）+ `to_openai_tools()` 导出 JSON Schema
- [x] T010 [P] [US3] 实现 `coding_agent/tools/files.py`：`read_file` / `write_file` / `edit_file`（old→new 唯一匹配替换）/ `apply_patch`（unified diff），越界写拦截
- [x] T011 [P] [US3] 实现 `coding_agent/tools/search.py`：`list_dir` / `glob` / `grep`（正则内容搜索）
- [x] T012 [P] [US3] 实现 `coding_agent/tools/bash.py`：命令执行（超时/退出码/stdout+stderr 捕获）+ 危险命令识别（`rm -rf`、`git push --force`、`dd` 等）
- [x] T013 [P] [US3] 实现 `coding_agent/tools/todo.py`：`todo_write`（pending/in_progress/completed 清单）
- [x] T014 [US3] 在 registry 注册全部工具 + 编写 `tests/test_tools.py`（依赖 T009–T013）

**Checkpoint**: 工具集可独立使用，单测通过

---

## Phase 4: User Story 4 - 可靠地解析模型输出并终止循环 (Priority: P2)

**Goal**: 健壮解析 `tool_calls`（含畸形 JSON 修复与降级）

**Independent Test**: 用样例 JSON 验证解析：正常 tool_calls、缺失字段、畸形 JSON、空文本最终回答

### Implementation

- [x] T015 [US4] 实现 `coding_agent/parsing.py`：`tool_calls` 结构化解析 + JSON 修复（补引号/去尾部垃圾）+ 降级策略
- [x] T016 [P] [US4] 编写 `tests/test_parsing.py`（正常/畸形/缺失字段/多工具调用）

**Checkpoint**: 解析模块对坏输入不崩溃，可单测通过

---

## Phase 5: User Story 2 - 与模型进行多轮对话并管理上下文 (Priority: P1)

**Goal**: 对话历史维护 + token 预算感知 + 三级压缩（裁剪旧工具结果 → 摘要压缩 → 保留最近 N 条）

**Independent Test**: 构造长历史验证压缩触发、摘要保留关键信息、不超上下文上限

### Implementation

- [x] T017 [US2] 实现 `coding_agent/messages.py`：`Message`/`Conversation` 模型 + token 估算 + 三级压缩/摘要（micro-compact + auto-compact）
- [x] T018 [P] [US2] 编写 `tests/test_messages.py`（历史增长、触发压缩、摘要信息保留）

**Checkpoint**: 上下文管理可独立单测

---

## Phase 6: User Story 1 - 完成一个端到端的编程任务 (Priority: P1) 🎯 MVP

**Goal**: agent 主循环——「决策 → 解析 → 执行 → 回传 → 终止」，这是整个项目的核心闭环

**Independent Test**: 用 mock LLM 模拟「调用 read_file → 调用 edit_file → 调用 bash → 最终回答」序列，验证循环推进、结果回传、正确终止

### Implementation

- [x] T019 [US1] 实现 `coding_agent/agent.py` 主循环：集成 llm/registry/parsing/messages，终止条件 = `finish_reason=="stop"` + `max_steps` + 连续失败阈值（依赖 T008、T009、T015、T017）
- [x] T020 [US1] 实现最小 CLI 入口 `coding_agent/cli.py`（单次任务：`python -m coding_agent "任务"`，打印最终结果）
- [x] T021 [P] [US1] 编写 `tests/test_loop.py`（mock LLM 驱动完整多轮循环 + 终止 + 失败恢复）

**Checkpoint**: 🎯 MVP 达成——能对一个真实任务跑通「读代码 → 改代码 → 跑命令 → 交付」

---

## Phase 7: User Story 5 - 凭据与配置的安全管理 (Priority: P3)

**Goal**: 凭据仅经环境变量/未入库配置，缺失时清晰报错，绝不回显明文

**Independent Test**: 无 key 启动报错、key 优先级正确、日志不含明文

### Implementation

- [ ] T022 [US5] 在 `coding_agent/config.py` 补强凭据读取与校验（缺失时清晰报错 + 来源优先级 + 禁止明文回显）
- [ ] T023 [P] [US5] 编写 `tests/test_cli.py`（key 来源优先级、缺失报错、不泄露明文）

**Checkpoint**: 合规项满足（FR-010/FR-011）

---

## Phase 8: User Story 6 - 演示友好的交互与安全可控执行 (Priority: P3)

**Goal**: 流式 UI + 会话续跑 + 交互式 REPL，支撑 2 分钟演示

**Independent Test**: 运行多步任务观察实时渲染、危险命令弹出确认、中断后 `--continue` 恢复

### Implementation

- [ ] T024 [US6] 实现 `coding_agent/ui.py`：`rich` 流式渲染、工具调用面板、彩色 unified diff、危险命令 `[y/N]` 确认
- [ ] T025 [US6] 实现 `coding_agent/session.py`：会话 JSONL 持久化 + `--continue` 续跑（`~/.coding-agent/sessions/*.jsonl`）
- [ ] T026 [US6] 完善 `coding_agent/cli.py`：交互式 REPL + 参数 `--model/--cwd/--max-steps/--auto-approve/--continue/--session/--verbose`

**Checkpoint**: 演示体验完整（FR-014/FR-016/FR-017/FR-018）

---

## Phase 9: User Story 7 - 自定义 Skill 加载 (Priority: P3 / 加分项)

**Goal**: 像 Claude Code 一样加载自定义 SKILL.md，按需注入领域能力

**Independent Test**: 创建示例 skill，验证能被扫描列出、在相关任务中触发加载并注入指令

### Implementation

- [ ] T027 [US7] 实现 `coding_agent/skill.py`：扫描 SKILL.md、解析 frontmatter（name/description/triggers）、按需加载注入（借鉴 learn-claude-code s05 与 opencode skill）
- [ ] T028 [P] [US7] 创建示例 skill `skills/agent-builder/SKILL.md`（含元数据 + 指令正文 + 可选 `references/`）
- [ ] T029 [US7] 将 skill 接入 registry：新增 `list_skills` 工具 + 触发加载逻辑

**Checkpoint**: 自定义 skill 可用（FR-019）

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: 交付收尾

- [ ] T030 [P] 编写 `README.txt`（≤1000 汉字：仓库地址/如何运行/特色功能/实现思路，符合 requirement.md 提交要求）
- [ ] T031 端到端演示验证：按 `specs/001-coding-agent/quickstart.md` 流程走通真实任务（含测试失败 → 读报错 → 自纠 → 通过 → 展示 diff）
- [ ] T032 [P] 边界测试与代码清理：命令超时、越界写拦截、破坏性命令拦截、Ctrl-C 优雅退出

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (P1)**: 无依赖，立即开始
- **Foundational (P2)**: 依赖 Setup，**阻塞所有 user story**
- **US3/US4/US2 (P3–P5)**: 依赖 Foundational，三者相互独立可并行
- **US1 (P6, MVP)**: 依赖 US3 + US4 + US2（主循环集成三者）
- **US5/US6 (P7–P8)**: 依赖 US1（凭据补强与 UI 建立在能跑通的闭环上）
- **US7 (P9)**: 依赖 Foundational（可与 US6 并行）
- **Polish (P10)**: 依赖所有目标 story

### User Story Dependencies

- **US1（核心闭环）**: 是「整合型」story，依赖 US2/US3/US4 —— 因此虽为 P1 价值，但实现排在 US2/US3/US4 之后
- **US2 / US3 / US4**: 相互独立，可并行实现（纯函数，均可用 mock/单元测试独立验证）
- **US5 / US6 / US7**: 增强项，依赖核心闭环稳定

### Within Each User Story

- 纯函数实现 → 单元/集成测试 → 注册/集成
- 每个 story 完成即可独立验证

### Parallel Opportunities

- Setup 内 T003/T004 可并行；Foundational 内 T006/T007 可并行
- US3 内 T010/T011/T012/T013 可并行（不同文件）
- US2/US3/US4 三个 story 整体可并行推进
- US7 可与 US6 并行

---

## Parallel Example: User Story 3

```bash
# 四个工具文件互不依赖，可同时实现：
Task: "实现 coding_agent/tools/files.py"
Task: "实现 coding_agent/tools/search.py"
Task: "实现 coding_agent/tools/bash.py"
Task: "实现 coding_agent/tools/todo.py"
```

---

## Implementation Strategy

### MVP First（先跑通闭环）

1. Phase 1 Setup + Phase 2 Foundational
2. Phase 3–5（US3 工具 → US4 解析 → US2 上下文）
3. Phase 6（US1 主循环）→ **STOP 验证**：真实任务端到端跑通
4. 此时已具备可演示能力，可先录制演示、再增量增强

### Incremental Delivery（增量）

- MVP 后依次加 US5 凭据安全 → US6 演示 UI/续跑 → US7 skill → Polish
- 每阶段增量不影响已完成的闭环

### Solo Build 建议顺序（3 天）

- **Day 1**: Phase 1–4（骨架 + 底座 + 工具 + 解析）—— 纯函数，可完全离线测试
- **Day 2**: Phase 5–6（上下文 + 主循环）—— 用 mock LLM 离线调通循环，再用 DeepSeek 真跑
- **Day 3**: Phase 7–10（凭据 + UI/续跑 + skill + 收尾）—— 打磨演示 + README.txt + 视频

---

## Notes

- `[P]` = 不同文件、无依赖，可并行
- `[USn]` = 归属 user story，用于追踪
- mock LLM 测试让循环逻辑可离线迭代，节省 API 额度，是本项目「3 天交付」的关键工程手段
- 每完成一个逻辑分组提交一次 git，保留完整提交历史（requirement.md 要求）
