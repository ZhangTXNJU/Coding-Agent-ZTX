# Phase 0 — Research & Decisions

本文件记录实现前的关键技术决策。参考来源：`learn-claude-code`（教学范式）、`opencode`（开源架构）、`requirement.md`（硬约束）。

## D1 — 实现语言：Python 3.11+

- **Decision**: 用 Python 3.11+ 实现。
- **Rationale**: 3 天交付窗口下开发速度最快；参考教学项目 `learn-claude-code` 即为 Python，agent 循环范式可直接迁移；`openai` SDK 流式与 tool calling 支持成熟。
- **Alternatives**: TypeScript/Node（与 Claude Code/Codex/OpenCode 同栈、更产品化，但搭建与调试成本更高，弃用）。

## D2 — 模型接入：OpenAI 兼容 chat/completions + 原生 function calling

- **Decision**: 用 `openai` SDK 指向 OpenAI 兼容端点，模型用原生 `tools` + `tool_calls`（function calling），默认 `deepseek-chat`（`https://api.deepseek.com`）。
- **Rationale**: `requirement.md` 明确允许「模型厂商的 API 客户端库、OpenAI 兼容网关及模型原生的 tool calling」；OpenAI 兼容是覆盖 DeepSeek/GLM/Qwen/Kimi/MiniMax 的最大公约数。OpenCode 的 `openai-compatible` provider 正是这一模式。
- **Alternatives**: Anthropic Messages API（`learn-claude-code` 用此，但 DeepSeek 等国内厂商的 OpenAI 兼容更普遍）；手写 HTTP（放弃 SDK 流式与重试便利，收益低）。

## D3 — 工具集：read / write / edit / apply_patch / list / glob / grep / bash / todo_write

- **Decision**: 8 个核心工具，覆盖「感知 + 行动 + 规划」三类。
- **Rationale**: 对齐 OpenCode 的 `tool/`（read.ts、edit.ts、apply_patch.ts、glob、grep、shell、todo）与 Claude Code 的核心工具。`edit`/`apply_patch` 提供**行范围/差异式精准编辑**，是「更强」的关键差异点（优于整文件重写）。
- **Alternatives**: 仅 read/write/bash 最小集（无法支撑真实规模任务，弃用）；加入 lsp/webfetch/websearch（加分项，核心闭环稳定后增量）。

## D4 — 上下文管理：token 预算感知 + 三级压缩

- **Decision**: `messages.py` 维护消息历史，估算 token；逼近上限时依次：① 裁剪最旧工具结果（micro-compact）② 用摘要模型把历史压缩为 summary（auto-compact）③ 只保留系统提示 + 摘要 + 最近 N 条。
- **Rationale**: 借鉴 `learn-claude-code` s06 的三层压缩与 OpenCode 的 `session/compaction.ts` + `agent/prompt/compaction.txt`。自写压缩逻辑是题目点名的核心。
- **Alternatives**: 简单截断丢历史（易丢关键信息，弃用）；向量 RAG 检索（过度设计，v1 不需要）。

## D5 — 输出解析：pydantic 校验 + JSON 修复 + 重试降级

- **Decision**: 用 pydantic 建模 `tool_calls` 结构；解析失败时做 JSON 修复（补引号/去尾部垃圾），仍失败则回传错误让模型重试一次，再失败则安全终止。
- **Rationale**: 模型偶发输出畸形 JSON，健壮解析是避免崩溃的关键；符合 spec FR-008。
- **Alternatives**: 正则宽松提取（脆弱）；直接崩溃（不可接受）。

## D6 — 循环终止：finish_reason + 最大步数 + 连续失败阈值

- **Decision**: 当响应 `finish_reason == "stop"`（无 `tool_calls`）时返回最终回答；叠加 `max_steps`（默认 30）与「连续失败阈值」（默认 3 次）双保险。
- **Rationale**: 与 `learn-claude-code` 的 `stop_reason != "tool_use"` 同构；终止条件是题目点名的核心。
- **Alternatives**: 仅靠模型自觉停止（可能死循环）；仅靠最大步数（可能过早/过晚）。

## D7 — 终端 UI：rich 流式渲染 + 彩色 diff + 审批

- **Decision**: `rich` 实现逐 token 流式输出、工具调用面板、彩色 unified diff、危险命令 `[y/N]` 确认。
- **Rationale**: `rich` 是纯 UI 库（非 agent 框架），显著提升演示观感（spec FR-018 / Story 6）。
- **Alternatives**: `textual`（更重、需重构为异步框架）；纯 ANSI 手写（工作量大）。

## D8 — 会话持久化：JSONL + 续跑

- **Decision**: 每轮消息追加到 `~/.coding-agent/sessions/<id>.jsonl`；`--continue` 重放恢复。
- **Rationale**: JSONL 追加写、可读、易调试；满足 spec FR-017。
- **Alternatives**: SQLite（更结构化但 v1 过度）；内存 only（无法续跑）。

## D9 — 权限边界：工作目录限制 + 危险命令识别 + 超时

- **Decision**: `bash` 工具默认在受控 cwd 执行，识别 `rm -rf`/`git push --force`/`dd` 等危险模式并要求确认；命令设超时（默认 120s）；文件写入限制在 cwd 内。
- **Rationale**: 满足 spec FR-013/FR-016；对齐 OpenCode 的 `permission/` 与 `tool/shell` 的审批机制。
- **Alternatives**: 容器/沙箱强隔离（超纲，题目允许弱边界）。
