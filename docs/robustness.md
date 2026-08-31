# 工具输出与上下文安全（Robustness）总结

> 分支：`005-agent-robustness`　日期：2026-08-31

本文总结针对 agent 在「长输出、交互输入、上下文膨胀」三类场景下的加固方案，设计思路仿照 Claude Code 与 OpenCode 的成熟做法。

## 一、要解决的问题

| # | 问题 | 未加固前的表现 |
|---|------|---------------|
| 1 | 命令输出很长 | `bash` 把 stdout/stderr **原样**塞进上下文，一次 `cat 大文件` 或编译刷屏就能撑爆记忆窗口 |
| 2 | 运行程序要交互输入（账号/密码） | stdin 继承父进程终端，命令会**卡住**等输入（UI 看起来冻结），靠 120s 超时兜底 |
| 3 | 大文件被整读 | `read_file` 静默截断到 256KB，模型误以为读到了全文 |
| 4 | 上下文无预算检查 | `estimate_tokens` / `needs_compaction` 已写但**从未接线** |
| 5 | 无自动压缩 | `trim_tool_results` / `compact` 已写但**从未接线** |

## 二、修复总览（对照成熟 agent）

| 维度 | 本实现 | Claude Code / OpenCode 的做法 |
|------|--------|------------------------------|
| 长输出截断 | `truncate_text` 头尾保留 + 省略标记 | 工具层截断，头尾 + `[truncated]` 标记 |
| 大文件拒读 | 超过 256KB 且未给 offset/limit 时**拒绝**并提示 grep/分片 | Read 超限拒绝，引导 grep |
| 非交互化 | `stdin=DEVNULL` + 封死 `GIT_TERMINAL_PROMPT` 等 | stdin 关闭 + 非交互环境变量 + prompt 引导用 `--yes` |
| 预算检查 | 每步循环前 `needs_compaction()` 前置检查 | 逼近上限前就触发压缩 |
| 自动压缩 | 三级：截断 → 折叠旧消息为摘要 | auto-compact（旧消息摘要化） |

## 三、详细实现

### 1. 长度截断（`messages.py` + `agent.py`）

新增 `truncate_text(text, max_chars)`：保留首尾各一半，中间插入省略标记，超长文本不再整体进入上下文。

- 写入上下文前截断：`agent.py` 主循环在 `add_tool` 前调用 `truncate_text(result, config.max_tool_result_chars)`（默认 20_000 字符）。
- `trim_tool_results`（一级压缩）也复用同一 helper，去掉重复代码。

### 2. 大文件超限拒读（`tools/files.py`）

`read_file` 改为：先用 `path.stat().st_size` 判断大小，超过 `_MAX_READ_BYTES`（256KB）**且未指定 offset/limit** 时抛错：

```
文件过大（N 字节，上限 262144），已拒绝整读。请用 grep 定位关键行，或用 read_file 指定 offset/limit 分片读取。
```

指定了 offset/limit 则放行分片读取（让模型能定点读大文件的局部）。这样避免了「静默截断让模型误以为读全了」的误导。

### 3. 非交互化（`tools/bash.py`）

`run_bash` 增加两层防护：

1. `stdin=subprocess.DEVNULL` —— 需要输入的程序立刻读到 EOF 快速失败，而不是挂起。
2. 注入非交互环境变量 `_NONINTERACTIVE_ENV`：
   - `GIT_TERMINAL_PROMPT=0`（封死 git 凭据提示）
   - `DEBIAN_FRONTEND=noninteractive`（封死 apt 交互）
   - `PYTHONUNBUFFERED=1`（Python 输出不缓冲）
   - `PIP_NO_INPUT=1`（封死 pip 交互）

同时更新 `bash` 工具描述与 SYSTEM_PROMPT，引导模型用非交互 flag（`--yes` / `-y` / `--no-input`）。

### 4. 上下文自动检查（`agent.py`）

主循环每步调用 `client.chat` 前先执行 `_compact_if_needed()`，用 `needs_compaction()`（估算 token 与 `max_tokens` 对比）做**前置**检查，超预算即触发压缩，而不是等模型报错。

预算 `max_tokens` 从配置读入（默认 48_000，给 DeepSeek 64K 留余量），并在 `run()` 开始时写入 `conversation.max_tokens`。

### 5. 自动压缩（三级，`messages.py` + `agent.py`）

```
_compact_if_needed():
    1. 若未超预算 → 返回
    2. trim_tool_results()          # 一级：裁剪超长工具结果（首尾保留）
    3. 若仍超预算 → compact()       # 二/三级：把较早消息折叠为摘要，保留最近 keep_recent 条
```

`compact()` 做了两处健壮性修正：

- **边界安全**：切点必须落在非 `tool` 消息上。若尾部以孤立的 tool 消息开头（其 `assistant(tool_calls)` 已被折叠），会破坏 OpenAI 的 `assistant(tool_calls)→tool` 配对，故向前推进切点。
- **累积摘要**：二次压缩时把上一轮摘要并入本轮待折叠内容，避免更早历史被丢弃。

当前摘要器为确定性的 `messages_to_text`（把旧消息折叠成纯文本，工具结果截到 500 字符）——这是无 LLM 调用的第一版，语义化 LLM 摘要见「后续工作」。

## 四、配置项

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `CODING_AGENT_MAX_TOKENS` | `48000` | 上下文预算（估算 token） |
| `CODING_AGENT_MAX_TOOL_RESULT_CHARS` | `20000` | 单次工具结果写入上下文前的截断上限 |

## 五、测试

新增 9 个测试（共 105 个全部通过）：

- `messages`：`truncate_text` 头尾截断 / 短文本 no-op / `compact` 边界安全（尾部不以 tool 开头）/ 累积摘要不丢失。
- `tools`：大文件拒读 / offset/limit 分片放行 / `bash` 非交互（stdin=DEVNULL + 环境变量）。
- `loop`：工具结果写入上下文前被截断 / 超预算自动触发压缩。
- `config`：新增默认值断言。

## 六、已知限制与后续工作

1. **内存峰值仍由 timeout 兜底**：`bash` 用 `subprocess.run(capture_output=True)` 一次性读入全部输出，极端场景（如 `cat /dev/urandom`）靠超时止损，未实现 Claude Code 那样的「Popen 增量读取 + 字节上限」。后续可改为流式读 + 超限即 kill。
2. **摘要为确定性 flatten，非 LLM 语义摘要**：`messages_to_text` 只是把旧消息折叠成文本，不产生真正的语义摘要；长会话仍会累积。后续可在 `LLMClient` 增加 `summarize()` 用一次无工具调用做语义摘要。
3. **token 估算粗略**：`estimate_tokens` 按「CJK=1 token、其余 4 字符 1 token」估算，不精确；真实预算应参考目标模型的上下文窗口。
4. **offset/limit 读大文件仍整读进内存**：分片读取目前是「先读全文件再切行」，对超大文件不理想；后续可改为按行流式读取。
