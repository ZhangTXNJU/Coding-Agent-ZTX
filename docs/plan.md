# 开发计划：编程智能体（Coding Agent）

> 本文件是面向阅读的工程计划摘要。正式的 spec-kit 工件见 `specs/001-coding-agent/`。

## 1. 目标

自研一个编程智能体 CLI：用户用自然语言下达编程任务，agent 通过与 LLM 多轮交互，**自主读写文件、在终端执行指令跑代码，并根据命令输出决定下一步行动**，完成「读代码 → 改代码 → 验证」的闭环。对标 Claude Code / Codex / OpenCode 的体验。

**硬约束**（来自 requirement.md）：不得使用任何 agent 框架/SDK；五块核心逻辑必须自写——**对话历史与上下文管理、工具定义与本地执行、模型输出解析、循环终止条件、错误处理**；凭据仅经环境变量/未入库配置。

## 2. 技术栈

| 项 | 选择 |
|----|------|
| 语言 | Python 3.11+ |
| 模型接入 | OpenAI 兼容 `chat/completions` + 原生 function calling，默认 DeepSeek（可切 GLM/Qwen/Kimi/MiniMax） |
| 依赖 | `openai`（客户端）、`rich`（终端 UI）、`pydantic`（校验）、`python-dotenv`（env）、`pytest`（测试） |
| 禁用 | LangChain / LlamaIndex / Agent SDK / AutoGen / CrewAI 等一切 agent 框架 |

## 3. 架构

```
coding_agent/
├── cli.py         # 入口 + 交互式 REPL
├── config.py      # 三级配置（env/.env/config.toml）
├── llm/
│   ├── client.py      # OpenAI 兼容流式客户端（薄封装）
│   └── providers.py   # 端点注册表
├── agent.py       # ★ agent 主循环
├── messages.py    # ★ 上下文管理（token 预算 + 三级压缩）
├── parsing.py     # ★ tool_calls 解析 + JSON 修复
├── errors.py      # ★ 重试/退避
├── session.py     # 会话持久化 + 续跑
├── ui.py          # rich 流式 + 彩色 diff + 审批
├── skill.py       # 自定义 SKILL.md 加载
└── tools/         # ★ 工具定义与本地执行
    ├── registry.py / files.py / search.py / bash.py / todo.py
```

关键点：`llm/` 只做客户端封装，**编排逻辑 100% 自写**，满足「不用 agent 框架」的硬约束。

## 4. 核心机制（题目点名的五块）

1. **上下文管理**：维护消息历史，token 预算感知；逼近上限时三级压缩（裁剪旧工具结果 → 摘要压缩 → 保留最近 N 条）。
2. **工具定义与本地执行**：注册表 `name → (description, schema, handler)`，全部本地执行，不依赖服务端托管。
3. **输出解析**：pydantic 校验 + JSON 修复 + 重试降级，畸形输出不崩溃。
4. **循环终止**：`finish_reason=="stop"`（模型交回最终回答）+ 最大步数 + 连续失败阈值三重保险。
5. **错误处理**：API 指数退避重试、命令超时、工具错误回传让模型自纠。

## 5. 功能清单

**核心工具（8 个）**：`read_file` / `write_file` / `edit_file`（行级精准替换）/ `apply_patch`（diff 补丁）/ `list_dir` / `glob` / `grep` / `bash` / `todo_write`。

**增强能力**：
- diff 式精准编辑（非整文件重写）
- rich 流式渲染 + 彩色 diff
- 危险命令审批门（`rm -rf` / `git push --force` 等）
- 会话续跑（`--continue`）
- **自定义 Skill**：像 Claude Code 一样加载 SKILL.md，按需注入领域能力（US7）

## 6. 代码量评估

| 模块 | 估 LOC |
|------|--------|
| agent 主循环 | ~150 |
| 上下文管理 (messages) | ~200 |
| 输出解析 (parsing) | ~150 |
| 错误处理 (errors) | ~100 |
| LLM 客户端 + 端点表 | ~280 |
| 工具集 (files/search/bash/todo) | ~680 |
| UI + CLI + config + session + skill | ~800 |
| **源码小计** | **~2,360** |
| 测试 (pytest) | ~700 |
| **合计** | **~3,000** |

3 天窗口内稳妥可达。

## 7. 构建顺序

1. Setup + Foundational（骨架 / 配置 / LLM 客户端 / 错误处理）
2. 工具集（US3）——纯函数，可离线单测
3. 输出解析（US4）
4. 上下文管理（US2）
5. **主循环（US1）🎯 MVP**——用 mock LLM 离线调通，再真跑 DeepSeek
6. 凭据安全（US5）→ 演示 UI + 续跑（US6）→ Skill（US7）→ 收尾

**时间分配**：Day 1 = 骨架+底座+工具+解析；Day 2 = 上下文+主循环；Day 3 = UI/续跑/skill + README.txt + 视频。

## 8. 预期效果

- **可运行**：`pip install -e .` + 填 key 即可跑。
- **可演示**：2 分钟视频展示「下达任务 → 流式读文件/改代码 → 跑测试失败 → 读报错自纠 → 再验证通过 → 展示彩色 diff」。
- **可解释**：README.txt 说明五块自写核心逻辑，评审一眼看出是自研 harness 而非套壳。

## 9. 参考

- `learn-claude-code`：agent 循环范式（s01）、上下文压缩（s06）、skill 加载（s05）
- `opencode`：provider 抽象、工具注册表、session 生命周期、permission 审批
- `requirement.md`：硬约束与提交要求
