# Quickstart — 快速上手

## 1. 环境准备

```bash
# Python 3.11+
python --version

# 创建虚拟环境并安装依赖
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## 2. 配置凭据

```bash
cp .env.example .env
# 编辑 .env，填入 API key（.env 已被 .gitignore 忽略）
#   CODING_AGENT_API_KEY=sk-xxx
#   CODING_AGENT_PROVIDER=deepseek
```

或直接导出环境变量：`export CODING_AGENT_API_KEY=sk-xxx`

## 3. 运行

```bash
# 单次任务
python -m coding_agent "在当前项目里给 CLI 新增 --dry-run 参数并补测试"

# 交互式 REPL
python -m coding_agent

# 续跑上次会话
python -m coding_agent --continue
```

## 4. 测试

```bash
pytest tests/ -v
```

## 5. 典型演示流程（2 分钟视频素材）

1. 启动 agent，下达「给示例项目加一个功能 + 补测试」任务
2. agent 流式输出思考与工具调用（read_file → edit_file → bash 跑测试）
3. 测试失败 → agent 读取报错 → 修正 → 再验证通过
4. 展示彩色 diff 与最终 `git diff` 结果
