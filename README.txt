自研编程智能体（Coding Agent）

一、Git 仓库地址
https://github.com/ZhangTXNJU/Coding-Agent-ZTX

二、如何运行
环境要求：Python ≥ 3.11。
1. 安装依赖：pip install -e .
2. 配置凭据：复制 .env.example 为 .env，填入 CODING_AGENT_API_KEY（任意 OpenAI 兼容服务的 key，默认 DeepSeek）。
3. 运行：
   · 单次任务：coding-agent "任务描述"
   · 交互式对话：coding-agent
   · 也可用 python -m coding_agent "任务描述"

三、特色功能
1. 自研闭环 harness：决策→解析→执行→回传→终止，不使用任何 agent 框架/SDK，核心逻辑全部手写。
2. 上下文管理：三级压缩（超长结果截断→LLM 语义摘要→确定性回退），长任务不丢关键信息。
3. 内置 15 个工具：文件读写、搜索、bash、后台任务、任务清单、子 agent 委托、联网抓取等。
4. Skill 系统：11 个内置 skill（代码审查、写测试、重构、写文档、讲代码等）+ 支持自定义 skill 与斜杠命令调用。
5. ask_user 主动澄清：需求或方案不确定时，agent 会抛出选项让用户拍板，而非自行猜测。
6. 子 agent 委托：task 工具把独立子任务交给子 agent，独立上下文执行。
7. 项目宪章：工作目录 Coding-Agent.md 作为最高优先级硬约束注入，跨会话持久。
8. 只读规划阶段：specify/clarify/plan/tasks 等需求规划 skill 自动禁用写文件与 bash。
9. 会话持久化：历史存 JSONL，支持 /continue 续跑。
10. 安全防护：危险命令确认、越界写入拦截、联网抓取 SSRF 防护、凭据仅经环境变量。

四、其它说明
· 技术栈：Python 3.11 + OpenAI 兼容 function calling（默认 DeepSeek，可切换 qwen/glm/kimi/minimax）。
· 测试：pytest，覆盖主循环、工具、上下文压缩、会话、skill、子 agent、SSRF 防护等，离线 mock 驱动完整闭环。
· 详细使用说明见仓库根目录 README.md。
