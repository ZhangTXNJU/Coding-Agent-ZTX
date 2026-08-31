# 任务清单

> 完整版（含依赖图与执行策略）见 `specs/001-coding-agent/tasks.md`。本文件为可勾选的执行清单。

## Phase 1 · Setup（项目初始化）

- [x] T001 创建 `pyproject.toml`（包名 `coding_agent`、Python 3.11+、entry point）
- [x] T002 声明依赖 `openai`/`rich`/`pydantic`/`python-dotenv` + `pytest`
- [x] T003 创建 `coding_agent/__init__.py` 与 `__main__.py` 骨架
- [x] T004 创建 `.env.example`，确认 `.gitignore` 忽略 `.env`

## Phase 2 · Foundational（阻塞性底座）

- [x] T005 实现 `config.py`（三级配置 + `AgentConfig`）
- [x] T006 实现 `llm/providers.py`（端点注册表）
- [x] T007 实现 `errors.py`（错误类型 + 退避重试）
- [x] T008 实现 `llm/client.py`（流式 chat + tool_calls）

## Phase 3 · US3 工具集（读/写/执行命令）

- [x] T009 实现 `tools/registry.py`（注册表 + schema 导出）
- [x] T010 实现 `tools/files.py`（read/write/edit/apply_patch）
- [x] T011 实现 `tools/search.py`（list_dir/glob/grep）
- [x] T012 实现 `tools/bash.py`（命令执行 + 超时 + 危险命令识别）
- [x] T013 实现 `tools/todo.py`（todo_write）
- [x] T014 注册全部工具 + `tests/test_tools.py`

## Phase 4 · US4 输出解析

- [x] T015 实现 `parsing.py`（tool_calls 解析 + JSON 修复）
- [x] T016 编写 `tests/test_parsing.py`

## Phase 5 · US2 上下文管理

- [x] T017 实现 `messages.py`（历史 + token 预算 + 三级压缩）
- [x] T018 编写 `tests/test_messages.py`

## Phase 6 · US1 端到端闭环 🎯 MVP

- [x] T019 实现 `agent.py` 主循环（决策→执行→回传→终止）
- [x] T020 实现最小 `cli.py`（单次任务入口）
- [x] T021 编写 `tests/test_loop.py`（mock LLM 离线测循环）

## Phase 7 · US5 凭据安全

- [ ] T022 补强 `config.py` 凭据读取与校验
- [ ] T023 编写 `tests/test_cli.py`

## Phase 8 · US6 演示交互

- [ ] T024 实现 `ui.py`（rich 流式 + 彩色 diff + 审批）
- [ ] T025 实现 `session.py`（JSONL 持久化 + 续跑）
- [ ] T026 完善 `cli.py`（REPL + 完整参数）

## Phase 9 · US7 自定义 Skill（加分项）

- [ ] T027 实现 `skill.py`（扫描 SKILL.md + 按需注入）
- [ ] T028 创建示例 skill `skills/agent-builder/SKILL.md`
- [ ] T029 接入 registry（list_skills + 触发加载）

## Phase 10 · 收尾

- [ ] T030 编写 `README.txt`（≤1000 汉字）
- [ ] T031 端到端演示验证（quickstart 流程走通）
- [ ] T032 边界测试 + 代码清理

---

**共 32 个任务**。关键里程碑：**Phase 6 = MVP**（真实任务端到端跑通）。每完成一个逻辑分组提交一次 git。
