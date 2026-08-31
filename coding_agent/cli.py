"""命令行入口：单次任务 + 交互式 REPL。

- 传任务（`python -m coding_agent "任务"`）：跑一轮后退出（等价 `claude -p`）。
- 不传任务且在交互终端：进入 REPL，持续对话并持久化会话。
"""
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
    p.add_argument("task", nargs="?", help="自然语言编程任务（缺省进入交互式 REPL）")
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

    return _run(config, args)


def _build(config: AgentConfig, args):
    """组装 UI / client / registry / agent，注入流式渲染与确认回调。"""
    from .agent import SYSTEM_PROMPT, Agent
    from .llm.client import LLMClient
    from .messages import Conversation
    from .tools import ToolContext, build_default_registry
    from .ui import UI

    ui = UI(verbose=args.verbose)
    client = LLMClient(config)
    registry = build_default_registry()
    ctx = ToolContext(
        workdir=config.workdir,
        command_timeout=config.command_timeout,
        auto_approve=config.auto_approve,
    )
    agent = Agent(
        config,
        client,
        registry,
        Conversation(system_prompt=SYSTEM_PROMPT),
        ctx,
        on_text=ui.stream_text,
        on_tool_call=ui.tool_call,
        on_tool_result=ui.tool_result,
        verbose=args.verbose,
    )
    ctx.confirm = ui.confirm  # 危险命令 → 交互式 [y/N] 确认
    return ui, agent


def _run(config: AgentConfig, args) -> int:
    from .session import latest_session_id, load_session, save_session

    ui, agent = _build(config, args)

    # 会话恢复
    session_id: str | None = None
    if args.resume or args.session:
        session_id = args.session or latest_session_id()
        if session_id is None:
            ui.error("没有可续跑的会话（~/.coding-agent/sessions/ 为空）。")
            return 1
        try:
            agent.conversation = load_session(session_id)
        except AgentError as exc:
            ui.error(str(exc))
            return 1
        ui.info(f"已恢复会话 {session_id}")

    # 单次任务：跑一轮后退出（不落盘会话）
    if args.task:
        try:
            agent.run(args.task)
        except AgentError as exc:
            ui.error(str(exc))
            return 1
        ui.console.print()
        return 0

    # 无任务：交互终端进入 REPL，非交互终端打印用法提示
    if not sys.stdin.isatty():
        ui.error("未提供任务，且当前不是交互终端。")
        ui.info('用法：python -m coding_agent "你的任务"')
        return 0

    return _repl(ui, agent, config, session_id, save_session)


def _repl(ui, agent: object, config: AgentConfig, session_id: str | None, save_session) -> int:
    from .agent import SYSTEM_PROMPT
    from .messages import Conversation

    ui.logo(config.provider, config.resolved_model, str(config.workdir))
    ui.info("输入自然语言任务，Enter 提交；/help 查看命令，/exit 退出。")
    ui.console.print()

    while True:
        try:
            line = ui.prompt()
        except (EOFError, KeyboardInterrupt):
            ui.console.print()
            break

        line = line.strip()
        if not line:
            continue
        if line in ("/exit", "/quit", "exit", "quit"):
            ui.info("再见 👋")
            break
        if line in ("/help", "help"):
            ui.help()
            continue
        if line in ("/clear", "clear"):
            agent.conversation = Conversation(system_prompt=SYSTEM_PROMPT)
            ui.info("对话上下文已清空。")
            continue
        if line == "/session":
            ui.info(f"当前会话：{session_id or '（尚未保存）'}")
            continue
        if line.startswith("/"):
            ui.error(f"未知命令：{line}（输入 /help 查看）")
            continue

        try:
            agent.run(line)
        except AgentError as exc:
            ui.error(str(exc))
        ui.console.print()
        session_id = _save(ui, agent, config, session_id, save_session)

    return 0


def _save(ui, agent, config: AgentConfig, session_id: str | None, save_session) -> str | None:
    try:
        session_id = save_session(
            agent.conversation,
            provider=config.provider,
            model=config.resolved_model,
            workdir=str(config.workdir),
            session_id=session_id,
        )
        ui.info(f"会话已保存：{session_id}")
        return session_id
    except AgentError as exc:
        ui.error(f"会话保存失败：{exc}")
        return session_id


if __name__ == "__main__":
    raise SystemExit(main())
