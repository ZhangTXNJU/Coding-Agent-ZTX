# Implementation Plan: Coding Agent (编程智能体)

**Branch**: `001-coding-agent` | **Date**: 2026-08-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-coding-agent/spec.md`

## Summary

实现一个自研的编程智能体 CLI：用户用自然语言下达编程任务，agent 通过与 LLM 多轮交互，自主读写文件、执行 shell 命令，完成「读代码 → 改代码 → 验证」的闭环。核心是**自研 harness**——模型用 OpenAI 兼容的原生 function calling 驱动，我们只负责提供工具（手脚）、上下文管理（记忆）、权限边界（安全）与循环控制（终止）。

技术路线：Python 3.11+，通过 OpenAI 兼容 `chat/completions` 接口对接 DeepSeek（运行时可切换 GLM/Qwen/Kimi/MiniMax）。架构借鉴 OpenCode（provider 抽象 + 工具注册表 + session 生命周期 + permission），但缩小到单包 CLI、单会话规模，并完全自行实现题目要求的五块核心逻辑。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `openai`（OpenAI 兼容客户端，含流式）、`rich`（终端 UI）、`pydantic`（schema 校验）、`python-dotenv`（环境变量）。禁用任何 agent 框架/SDK。

**Storage**: 文件系统为主 —— 会话历史存 JSONL（`~/.coding-agent/sessions/*.jsonl`）、配置存 TOML。不引入数据库。

**Testing**: `pytest`（单元 + 集成，用 mock LLM 响应离线测试循环）

**Target Platform**: macOS / Linux 本地命令行

**Project Type**: CLI（单进程命令行工具）

**Performance Goals**: 单次工具调用（本地执行 + 结果回传）在 1–3 秒内完成；模型输出流式逐 token 渲染。

**Constraints**: 不得使用 agent 框架/SDK；对话历史/上下文、工具定义与本地执行、输出解析、循环终止、错误处理必须自写；凭据仅经环境变量或未入库配置。

**Scale/Scope**: 单用户、单会话；核心工具 8–9 个；预计 ~2.5k–3k LOC（含测试）；3 天内可交付。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 目前仍是未填充的模板（占位符），无已批准的项目宪法。因此本计划的治理约束以 `requirement.md` 的硬性规则为准：

| 约束 | 要求 | 本设计是否满足 |
|------|------|----------------|
| 禁用 agent 框架/SDK | 不得用 LangChain / LlamaIndex / Agent SDK / AutoGen / CrewAI 等 | ✅ 仅用 `openai` / `rich` / `pydantic` / `dotenv` |
| 自写核心逻辑 | 上下文管理、工具定义+本地执行、输出解析、终止条件、错误处理 | ✅ 全部在 `coding_agent/` 内自实现 |
| 不得依赖服务端托管执行 | 不用 Code Interpreter / Files API | ✅ 工具均在本地执行 |
| 凭据安全 | 仅环境变量/未入库配置，不出现在仓库/README/视频 | ✅ `.env` 入 ignore，`.env.example` 只含占位符 |

无违规项，无需 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/001-coding-agent/
├── plan.md              # 本文件
├── research.md          # Phase 0 输出：技术决策与理由
├── data-model.md        # Phase 1 输出：核心实体模型
├── quickstart.md        # Phase 1 输出：快速上手
├── contracts/
│   ├── cli.md           # CLI 命令契约
│   └── tools.md         # 工具 JSON Schema 契约
└── tasks.md             # Phase 2 输出（/speckit-tasks 生成）
```

### Source Code (repository root)

```text
coding_agent/                    # Python 包
├── __init__.py
├── __main__.py                  # `python -m coding_agent` 入口
├── cli.py                       # 命令行入口、参数解析、REPL 交互循环
├── config.py                    # 配置加载（env / .env / config.toml）
├── llm/
│   ├── __init__.py
│   ├── client.py                # OpenAI 兼容客户端封装（流式 + 重试）
│   └── providers.py             # 端点注册表（deepseek/qwen/glm/kimi/minimax/…）
├── agent.py                     # agent 主循环（决策→执行→回传→终止）
├── messages.py                  # 对话历史 + token 预算 + 压缩/摘要
├── parsing.py                   # tool_calls 解析 + JSON 修复 + 降级
├── errors.py                    # 错误类型 + 重试/退避策略
├── session.py                   # 会话持久化与续跑
├── ui.py                        # rich 流式渲染、diff 展示、审批提示
└── tools/
    ├── __init__.py
    ├── registry.py              # 工具注册表（name→schema+handler 分发）
    ├── files.py                 # read_file / write_file / edit_file / apply_patch
    ├── search.py                # list_dir / glob / grep
    ├── bash.py                  # 命令执行（超时、退出码、危险命令识别）
    └── todo.py                  # todo_write 任务清单

tests/
├── conftest.py                  # mock LLM fixture
├── test_parsing.py
├── test_tools.py
├── test_messages.py
├── test_loop.py
└── test_cli.py

pyproject.toml
.env.example
.gitignore
README.txt                       # 提交说明（≤1000 汉字）
```

**Structure Decision**: 单包 CLI。核心逻辑集中在 `agent.py` / `messages.py` / `parsing.py` / `tools/`，即题目点名的五块；`llm/` 只做薄封装（客户端 + 端点表），不含任何编排逻辑——编排全部自写。
