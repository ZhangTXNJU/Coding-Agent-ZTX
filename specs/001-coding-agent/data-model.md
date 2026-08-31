# Phase 1 — Data Model

核心实体及其关系。字段为逻辑描述，不含具体类型实现。

## Message（消息）

对话中的单条记录，按时间顺序构成对话历史。

| 字段 | 说明 |
|------|------|
| role | `system` / `user` / `assistant` / `tool` 之一 |
| content | 文本内容（可为空，当仅携带 tool_calls 时） |
| tool_calls | assistant 消息可携带的多个工具调用（见 ToolCall） |
| tool_call_id | tool 消息关联的调用 ID |

**约束**：assistant 要么有 `content`、要么有 `tool_calls`、要么两者皆有；`tool` 消息必须引用一个已存在的 `tool_call_id`。

## ToolCall（工具调用）

模型发起的一次工具调用请求。

| 字段 | 说明 |
|------|------|
| id | 调用唯一标识（回传结果时引用） |
| name | 工具名（必须在注册表中存在） |
| arguments | 工具参数（JSON 对象，须满足 input_schema） |

## ToolResult（工具执行结果）

工具本地执行后回传给模型的结果。

| 字段 | 说明 |
|------|------|
| tool_call_id | 关联的 ToolCall.id |
| content | 结果文本（文件内容、命令 stdout/stderr 等） |
| is_error | 是否执行失败 |

## Tool（工具定义）

一个可被模型调用的能力。

| 字段 | 说明 |
|------|------|
| name | 工具名 |
| description | 供模型理解用途与使用时机 |
| input_schema | 参数 JSON Schema（校验 arguments） |
| handler | 本地执行逻辑（函数） |

## Conversation（对话）

一条完整对话的容器，管理上下文生命周期。

| 字段 | 说明 |
|------|------|
| messages | 有序 Message 列表 |
| system_prompt | 系统提示（agent 角色、工具使用规范、安全边界） |
| token_usage | 近轮 token 估算 |
| summary | 被压缩历史的摘要（压缩后填充） |

**状态转换**：`active` →（触发压缩）→ `compacted`（旧消息折叠进 summary）。

## Session（会话）

跨进程持久化的任务单元，支持续跑。

| 字段 | 说明 |
|------|------|
| id | 会话 ID（如时间戳+随机串） |
| cwd | 工作目录 |
| config_ref | 关联的 AgentConfig |
| conversation | 对话内容 |
| created_at / updated_at | 时间戳 |
| status | `running` / `completed` / `interrupted` / `error` |

## AgentConfig（运行配置）

| 字段 | 说明 |
|------|------|
| model | 模型名（如 `deepseek-chat`） |
| base_url | OpenAI 兼容端点 |
| api_key_source | `env` / `.env` / 配置文件（不落盘明文） |
| max_steps | 最大循环步数（默认 30） |
| max_failures | 连续失败阈值（默认 3） |
| command_timeout | 命令超时秒数（默认 120） |
| workdir | 受控工作目录 |
| auto_approve | 是否跳过危险命令确认 |

## TodoItem（任务清单项）

`todo_write` 工具的载体。

| 字段 | 说明 |
|------|------|
| id | 序号 |
| content | 任务描述 |
| status | `pending` / `in_progress` / `completed` |

## 关系

```
Session 1──1 Conversation 1──* Message
Message 0──* ToolCall 1──1 ToolResult
Registry *──1 Tool (name → Tool)
Session 1──1 AgentConfig
Conversation 0──* TodoItem
```
