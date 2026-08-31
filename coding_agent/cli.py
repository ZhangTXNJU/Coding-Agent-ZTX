"""命令行入口。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import AgentConfig, load_config
from .errors import AgentError, ConfigError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="coding-agent",
        description="自研编程智能体：自然语言下达任务，agent 自主读写文件、执行命令。",
    )
    p.add_argument("task", nargs="?", help="自然语言编程任务（缺省进入交互式 REPL，后续阶段实现）")
    p.add_argument("--provider", help="模型提供商（deepseek/qwen/glm/kimi/minimax）")
    p.add_argument("--model", help="模型名")
    p.add_argument("--base-url", help="OpenAI 兼容端点")
    p.add_argument("--cwd", help="工作目录")
    p.add_argument("--max-steps", type=int, help="最大循环步数（默认 30）")
    p.add_argument("--auto-approve", action="store_true", help="跳过危险命令确认")
    p.add_argument("--continue", dest="resume", action="store_true", help="续跑上次会话")
    p.add_argument("--session", help="续跑指定会话 ID")
    p.add_argument("--verbose", action="store_true", help="打印完整消息与工具原始 JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config(
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            max_steps=args.max_steps,
            auto_approve=args.auto_approve or None,  # 仅显式开启才覆盖 env
            workdir=Path(args.cwd) if args.cwd else None,
        )
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 1

    if not config.api_key:
        print(
            "未检测到 API key。请设置环境变量 CODING_AGENT_API_KEY，或在 .env 中配置。",
            file=sys.stderr,
        )
        return 1

    if not args.task:
        print("交互式 REPL 尚未实现（后续阶段）。当前请传入任务，例如：")
        print('  python -m coding_agent "你好"')
        return 0

    return _run(config, args)


def _run(config: AgentConfig, args) -> int:
    from .agent import SYSTEM_PROMPT, Agent  # 延迟导入，避免 --help 依赖 openai
    from .llm.client import LLMClient
    from .messages import Conversation
    from .tools import ToolContext, build_default_registry

    client = LLMClient(config)
    registry = build_default_registry()
    ctx = ToolContext(
        workdir=config.workdir,
        command_timeout=config.command_timeout,
        auto_approve=config.auto_approve,
    )
    conversation = Conversation(system_prompt=SYSTEM_PROMPT)
    agent = Agent(
        config,
        client,
        registry,
        conversation,
        ctx,
        on_text=lambda t: sys.stdout.write(t),
        verbose=args.verbose,
    )
    try:
        agent.run(args.task)
    except AgentError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
