# subagent 能力总结

> 分支：`008-subagent`　日期：2026-08-31

本文总结 agent 的 subagent 能力：把独立子任务委托给子 agent 在独立上下文中完成，只回传最终结论，从而降低主对话的上下文噪音。设计仿照 Claude Code / OpenCode 的 `Task`/`task` 工具机制。

## 一、核心思想

**上下文预算的转移 + 隔离**：把子任务会产生的中间工具调用/输出挪进一个用完即弃的一次性窗口，主窗口只保留一条 O(1) 的结论。

| | 不委托（主流程直接做） | 委托给 subagent |
|---|---|---|
| 子任务中间过程 | 全部进主上下文（几十条 message） | 进子窗口，随后丢弃 |
| 主上下文增长 | O(子任务步数) | **O(1)**（一条结论） |

## 二、执行模型（v1：阻塞式、同进程）

subagent 是主循环里的一次普通 `task` 工具调用，**同进程、同步阻塞**：

```
Agent.run(主任务)
  └─ client.chat → 模型调用 task(prompt)
       └─ _execute_tool → registry.run("task", ...)
            └─ ctx.spawn_subagent(prompt)
                 └─ sub_agent.run(prompt)   # 子 agent 跑一个完整循环
                      └─ 返回最终字符串（中间消息丢弃）
       └─ 结论作为一条 tool 消息回传主对话，主循环继续
```

隔离是**逻辑上下文隔离**（全新的 `Conversation`），不需要 OS 进程隔离。Claude Code / OpenCode 的基本 subagent 也是同进程、前台同步执行，独立上下文窗口 = 独立消息历史。

## 三、实现要点

| 机制 | 做法 | 对应规格 |
|------|------|---------|
| 独立上下文 | `_spawn_subagent` 用全新 `Conversation(system_prompt=SUBAGENT_PROMPT)` | FR-009 |
| 禁嵌套 | 子 agent 工具集 = `registry.without("task")` | FR-014 |
| 独立上限 | `replace(config, max_steps=subagent_max_steps)`（默认 15） | FR-010 |
| 权限沿用 | 复制 `workdir/timeout/auto_approve/confirm/skills`，破坏性命令仍走 `confirm` | FR-012 |
| 结构化回报 | 捕获 `MaxStepsExceeded`/`MaxFailuresExceeded`/`AgentError` → `[子 agent 未完成/失败]`；空结果 → `[子 agent 未产出结果]` | FR-011 / FR-013 |

关键文件：

- `coding_agent/agent.py`：`Agent._spawn_subagent()` + `SUBAGENT_PROMPT` + SYSTEM_PROMPT 规则 8 + 构造时注入 `ctx.spawn_subagent`。
- `coding_agent/tools/task.py`：`TASK` 工具（参数 `prompt`，须自包含）。
- `coding_agent/tools/registry.py`：`ToolContext.spawn_subagent` 字段 + `ToolRegistry.without(name)`。
- `coding_agent/config.py`：`subagent_max_steps`（env `CODING_AGENT_SUBAGENT_MAX_STEPS`）。

## 四、配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `CODING_AGENT_SUBAGENT_MAX_STEPS` | `15` | 子 agent 最大循环步数（小于主循环的 30） |

## 五、测试

新增 10 个测试（`tests/test_subagent.py`，全仓 137 个全部通过）：

- `task` 工具注册 / 委托 / 缺 prompt / 无委托能力。
- `without()` 只移除目标工具。
- 子 agent 独立上下文（首轮不含主对话历史）+ 工具集不含 `task`。
- 超步数 → `[未完成]`；空结果 → `[未产出]`。
- 危险命令仍走 `confirm`（权限沿用）。
- 主循环集成：委托后主对话只有一条 tool 消息（结论），中间过程不进入。

## 六、已知限制与后续

1. **无并行/后台**：子 agent 阻塞主循环，主 agent 等待期间不干别的（对应 Claude Code 的 `run_in_background`）。
2. **无整体墙钟超时**：子 agent 时长仅受 `subagent_max_steps × 每条命令 timeout` 约束；可后续加整体 deadline。
3. **无命名子 agent 定义**：v1 是通用 `task` 工具；Claude Code/OpenCode 的「按 `.md`/frontmatter 定义专职 agent（含独立 system prompt / 工具集 / 模型）」留作 v2。
4. **无 `SendMessage` 续跑 / worktree 隔离**：均属进阶，未实现。
