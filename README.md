# Coding Agent — 自研编程智能体

一个从零手写的编程智能体（coding agent）harness：你用自然语言下达编程任务，agent 通过与大语言模型多轮交互，自主地**读写文件、搜索代码、执行 shell 命令**，完成「读代码 → 改代码 → 验证」的完整闭环。

核心是**自研 harness**——模型用 OpenAI 兼容的原生 function calling 驱动，我们只负责提供工具（手脚）、上下文管理（记忆）、权限边界（安全）与循环控制（终止）。**不使用任何 agent 框架 / SDK**（LangChain、LlamaIndex、Agent SDK 等），核心逻辑全部手写。

> 类似一个简化的 Claude Code / OpenCode / Codex。

---

## 核心特性

- **自研闭环**：决策 → 解析 → 执行 → 回传 → 终止，含输出解析与 JSON 修复、失败重试、超步数/连续失败终止。
- **上下文管理**：三级压缩（超长工具结果截断 → LLM 语义摘要 → 确定性折叠回退）+ 中文感知的 token 估算。
- **15 个内置工具**：文件读写、搜索、bash、后台任务、任务清单、子 agent 委托、联网抓取等（见下文）。
- **Skill 系统**：11 个内置 skill + 支持自定义 skill，斜杠命令一键调用。
- **子 agent**：`task` 工具把独立子任务委托给子 agent（独立上下文）。
- **主动澄清**：`ask_user` 工具——需求/方案不确定时，agent 主动抛出选项让你拍板，而非自行猜测。
- **项目宪章**：工作目录下的 `Coding-Agent.md` 作为最高优先级硬约束注入，跨会话持久。
- **只读阶段**：`specify` / `clarify` / `plan` / `tasks` 等需求规划 skill 自动禁用写文件与 bash。
- **会话持久化**：历史存 JSONL，支持续跑（`/continue`、`--continue`）。
- **安全**：危险命令交互确认、越界写入拦截、fetch 的 SSRF 防护、凭据仅经环境变量。

---

## 快速开始

### 1. 环境要求

- **Python ≥ 3.11**
- 一个 OpenAI 兼容模型服务的 API key（默认 DeepSeek）

### 2. 安装

```bash
git clone git@github.com:ZhangTXNJU/Coding-Agent-ZTX.git
cd Coding-Agent-ZTX

# 创建虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖（含命令行入口 coding-agent）
pip install -e .
```

### 3. 配置 API key

复制 `.env.example` 为 `.env` 并填入你的 key（`.env` 已被 `.gitignore` 忽略，**切勿提交**）：

```bash
cp .env.example .env
# 编辑 .env：
#   CODING_AGENT_API_KEY=sk-xxx
#   CODING_AGENT_PROVIDER=deepseek
```

也可以直接设置环境变量：

```bash
export CODING_AGENT_API_KEY=sk-xxx
```

### 4. 运行

```bash
# 单次任务：跑一轮后退出（等价 claude -p）
coding-agent "把 src/foo.py 里的 bug 修好并跑测试"

# 交互式 REPL：持续对话
coding-agent

# 也可以不安装、直接用模块运行（在仓库根目录）
python -m coding_agent "任务"
```

---

## 使用方式

### 单次任务 vs 交互 REPL

| 命令 | 行为 |
|---|---|
| `coding-agent "任务"` | 跑一轮任务后保存会话并退出 |
| `coding-agent` | 进入交互式 REPL，持续对话 |
| `coding-agent --continue` | 续跑上次会话（`--session <id>` 续跑指定会话） |

### 命令行参数

```
coding-agent [任务] [选项]

  --provider        模型提供商：deepseek / qwen / glm / kimi / minimax（默认 deepseek）
  --model           模型名（默认用提供商默认模型）
  --base-url        OpenAI 兼容端点
  --cwd             工作目录（默认当前目录）
  --max-steps       最大循环步数（默认 30）
  --auto-approve    跳过危险命令确认
  --continue        续跑上次会话
  --session <id>    续跑指定会话 ID
  --verbose         打印完整消息与工具原始 JSON
```

### 交互式命令（REPL 内）

| 命令 | 说明 |
|---|---|
| `/help` | 查看帮助 |
| `/exit` / `/quit` | 退出 |
| `/sessions` | 列出会话历史（别名 `/history`、`/list`） |
| `/continue [id]` | 续跑/切换会话（可用 ID 前缀或序号） |
| `/skills` | 列出全部 skill |
| `/skill <name>` | 查看某个 skill 的说明 |
| `/skill-name [提示]` | 直接调用某个 skill（如 `/code-review`） |
| `/clear` | 清空当前对话上下文 |
| `/session` | 显示当前会话 ID |

---

## 内置工具

| 工具 | 说明 |
|---|---|
| `read_file` | 读取文件（大文件拒读整读，支持 offset/limit 分片） |
| `write_file` | 创建/覆盖文件 |
| `edit_file` | 精准替换（old_string → new_string） |
| `apply_patch` | 应用 unified diff 补丁 |
| `list_dir` / `glob` / `grep` | 目录列举 / glob 查找 / 正则搜索 |
| `bash` | 非交互执行 shell 命令（危险命令需确认）；`background=true` 可后台运行长命令 |
| `bash_wait` | 查询/等待后台任务结果（配合 `bash` 的 `background=true`） |
| `todo_write` | 维护任务清单 |
| `ask_user` | 需求不确定时向用户提问并给出选项 |
| `use_skill` | 加载并触发某个 skill |
| `task` | 把独立子任务委托给子 agent |
| `charter` | 读取/追加项目宪章（`Coding-Agent.md`） |
| `fetch` | 联网抓取 URL（内置 SSRF 防护） |

---

## Skill 系统

内置 11 个 skill，覆盖常见编程场景与需求规划流程：

| Skill | 说明 |
|---|---|
| `code-review` | 分级审查代码，产出问题清单与改进建议 |
| `write-tests` | 为目标代码生成测试并验证通过 |
| `refactor` | 行为不变的等价重构 |
| `write-docs` | 编写 README / docstring / API 文档 |
| `explain-code` | 由整体到局部讲解代码 |
| `create-skill` | 创建/更新自定义 skill |
| `specify` | 澄清诉求、固化需求规格（**只读**） |
| `clarify` | 针对规格提出澄清问题（**只读**） |
| `plan` | 产出实现计划（**只读**） |
| `tasks` | 拆解为任务清单（**只读**，只写 todo） |
| `implement` | 按计划执行实现并验证 |

### 自定义 skill

把一个 markdown 文件放进 `~/.coding-agent/skills/`，下次启动即被自动发现：

```markdown
---
name: fix-tests
description: 定位并修复失败的测试
---
1. 用 bash 跑测试，收集失败用例
2. read_file 阅读失败用例与对应源码
3. 修复代码或测试，重新运行验证
4. 回报：改了哪些文件、如何验证通过
```

可选的 `read_only: true` 字段会把该 skill 标记为只读（触发后禁用写文件与 bash）。

---

## 项目宪章

在工作目录放一个 `Coding-Agent.md`，其内容会被注入 system prompt 作为**最高优先级硬约束**（独立于对话历史，压缩/折叠不会丢失）。适合固化「绝对不能改的内容、必须遵守的规范」等规则。agent 会在被要求时用 `charter` 工具自动追加条款。

---

## 项目结构

```
coding_agent/          # Python 包
├── cli.py             # 命令行入口、参数解析、REPL 交互循环
├── config.py          # 配置加载（env / .env）
├── agent.py           # agent 主循环（决策→执行→回传→终止）
├── messages.py        # 对话历史 + token 预算 + 压缩/摘要
├── parsing.py         # tool_calls 解析 + JSON 修复
├── errors.py          # 错误类型 + 重试/退避
├── session.py         # 会话持久化与续跑
├── skills.py          # skill 系统（内置 + 自定义）
├── charter.py         # 项目宪章加载
├── ui.py              # rich 流式渲染、diff 展示、审批提示
├── llm/               # OpenAI 兼容客户端 + 提供商端点表
└── tools/             # 工具定义与本地执行（files/search/bash/todo/ask_user/...）

tests/                 # 单元 + 集成测试（用 mock LLM 离线驱动完整闭环）
specs/                 # 需求/计划文档
```

---

## 测试

```bash
pip install -e ".[dev]"   # 安装 pytest
pytest                    # 运行全部测试
```

测试覆盖主循环、工具执行、上下文压缩、会话持久化、skill、子 agent、SSRF 防护等，用 mock LLM 响应离线驱动完整多轮闭环。

---

## 配置项

所有配置均可通过环境变量（或 `.env`）覆盖，命令行参数优先：

| 环境变量 | 说明 | 默认 |
|---|---|---|
| `CODING_AGENT_API_KEY` | API key（**必需**） | — |
| `CODING_AGENT_PROVIDER` | 提供商 | `deepseek` |
| `CODING_AGENT_MODEL` | 模型名 | 提供商默认 |
| `CODING_AGENT_BASE_URL` | OpenAI 兼容端点 | 提供商默认 |
| `CODING_AGENT_MAX_STEPS` | 最大循环步数 | `30` |
| `CODING_AGENT_COMMAND_TIMEOUT` | bash 超时（秒） | `120` |
| `CODING_AGENT_AUTO_APPROVE` | 跳过危险命令确认 | 关闭 |

支持的内置提供商：`deepseek`（默认）、`qwen`、`glm`、`kimi`、`minimax`，也可用 `--base-url` 对接任意 OpenAI 兼容服务。

---

## 安全说明

- API key 仅经环境变量或未入库的 `.env` 提供，绝不写入仓库。
- 危险命令（`rm -rf`、`git push --force`、`dd`、`mkfs` 等）执行前交互确认。
- 写文件越界（解析后路径落在工作目录之外）一律拦截。
- `fetch` 拒绝访问本机/内网/云元数据等非公网地址（SSRF 防护）。
- `charter` 写入是跨会话高影响操作，默认需用户确认。
