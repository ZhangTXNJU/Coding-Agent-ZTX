# Contract — CLI 命令接口

## 调用方式

```bash
# 单次任务（非交互）
python -m coding_agent "新增一个 --dry-run 命令行参数并补充测试"

# 交互式 REPL（不传任务，进入多轮对话）
python -m coding_agent
```

## 命令行参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `task` | 位置参数：自然语言任务描述 | 无（缺省进入 REPL） |
| `--model` | 模型名 | `deepseek-chat` |
| `--base-url` | OpenAI 兼容端点 | 按 provider 解析 |
| `--cwd` | 工作目录 | 当前目录 |
| `--max-steps N` | 最大循环步数 | 30 |
| `--auto-approve` | 跳过危险命令确认 | 关 |
| `--continue` | 续跑最近一次会话 | 关 |
| `--session ID` | 续跑指定会话 | 无 |
| `--verbose` | 打印完整消息与工具原始 JSON | 关 |

## 环境变量

| 变量 | 说明 |
|------|------|
| `CODING_AGENT_API_KEY` | API 凭据（首选来源） |
| `CODING_AGENT_MODEL` | 模型名（命令行优先） |
| `CODING_AGENT_BASE_URL` | 端点覆盖 |
| `CODING_AGENT_PROVIDER` | `deepseek` / `qwen` / `glm` / `kimi` / `minimax` / `custom` |

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 任务正常完成 |
| 1 | 运行错误（配置缺失、API 失败、达到终止阈值等） |
| 130 | 用户 Ctrl-C 中断 |

## 配置优先级（高→低）

命令行参数 → 环境变量 → `.env` → `config.toml` → 内置默认。
