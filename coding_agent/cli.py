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

    try:
        return _run(config, args)
    finally:
        # 会话结束（单次任务跑完 / REPL 退出 / 异常中断）统一回收后台长任务，
        # 避免脱离进程组的孤儿进程与临时日志文件泄漏。后台任务本身跨对话轮次存活。
        from .tools.bash import cleanup_background_tasks

        cleanup_background_tasks()


def _build(config: AgentConfig, args):
    """组装 UI / client / registry / agent，注入流式渲染与确认回调。"""
    from .agent import Agent, build_system_prompt
    from .charter import load_charter
    from .llm.client import LLMClient
    from .messages import Conversation
    from .skills import DEFAULT_SKILLS_DIR, build_skill_registry
    from .tools import ToolContext, build_default_registry
    from .ui import UI

    ui = UI(verbose=args.verbose)
    client = LLMClient(config)
    registry = build_default_registry()

    skills, skill_errors, skill_warnings = build_skill_registry(DEFAULT_SKILLS_DIR)
    for err in skill_errors:
        ui.error(f"skill 加载失败：{err}")
    for warn in skill_warnings:
        ui.info(f"skill：{warn}")

    # 项目宪章：读取工作目录 Coding-Agent.md，注入 system prompt（最高优先级硬约束）
    charter_text, _ = load_charter(config.workdir)
    if charter_text:
        ui.info(f"已加载项目宪章 Coding-Agent.md（{len(charter_text)} 字符）")

    ctx = ToolContext(
        workdir=config.workdir,
        command_timeout=config.command_timeout,
        auto_approve=config.auto_approve,
        skills=skills,
    )
    agent = Agent(
        config,
        client,
        registry,
        Conversation(system_prompt=build_system_prompt(skills, charter_text)),
        ctx,
        on_text=ui.stream_text,
        on_tool_call=ui.tool_call,
        on_tool_result=ui.tool_result,
        verbose=args.verbose,
        charter_text=charter_text,
    )
    ctx.confirm = ui.confirm  # 危险命令 → 交互式 [y/N] 确认
    ctx.ask_user = ui.ask_user  # 需求/方案不确定 → 交互式选项提问
    ui.bind_context(ctx)  # 实时任务面板读取 todos
    ui.bind_skills(skills.list())  # 斜杠补全菜单读取 skill
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
            agent.replace_conversation(load_session(session_id))
        except AgentError as exc:
            ui.error(str(exc))
            return 1
        ui.info(f"已恢复会话 {session_id}")

    # 单次任务：跑一轮后保存会话并退出
    if args.task:
        try:
            agent.run(args.task)
        except AgentError as exc:
            ui.error(str(exc))
            return 1
        ui.end_stream()
        _save(ui, agent, config, session_id, save_session)
        return 0

    # 无任务：交互终端进入 REPL，非交互终端打印用法提示
    if not sys.stdin.isatty():
        ui.error("未提供任务，且当前不是交互终端。")
        ui.info('用法：python -m coding_agent "你的任务"')
        return 0

    return _repl(ui, agent, config, session_id, save_session)


def _repl(ui, agent: object, config: AgentConfig, session_id: str | None, save_session) -> int:
    from .messages import Conversation
    from .session import load_session

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
        if line in ("/sessions", "/history", "/list"):
            _list_sessions(ui)
            continue
        if line == "/skills":
            _list_skills(ui, agent)
            continue
        # /skill-name → 直接调用 skill（Claude Code 风格斜杠命令，可追加自然语言提示）
        invocation = _resolve_skill_invocation(line, agent.ctx.skills)
        if invocation is not None:
            skill, rest = invocation
            ui.info(f"调用 skill：{skill.name} · {skill.description}")
            task = rest or f"请执行 {skill.name} 这个 skill"
            try:
                agent.run(task, skill=skill)
            except AgentError as exc:
                ui.error(str(exc))
            ui.end_stream()
            session_id = _save(ui, agent, config, session_id, save_session)
            continue
        if line.startswith("/skill"):
            _show_skill(ui, agent, line[len("/skill"):].strip())
            continue
        if line.startswith("/continue"):
            target = line[len("/continue"):].strip() or None
            new_sid = _resolve_session(ui, target)
            if new_sid:
                try:
                    agent.replace_conversation(load_session(new_sid))
                    session_id = new_sid
                    ui.info(f"已切换到会话 {new_sid}")
                except AgentError as exc:
                    ui.error(str(exc))
            continue
        if line in ("/clear", "clear"):
            agent.replace_conversation(Conversation(system_prompt=agent.system_prompt))
            session_id = None
            ui.info("对话上下文已清空（下次保存将作为新会话）。")
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
        ui.end_stream()
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


def _list_sessions(ui) -> None:
    """列出全部会话历史（最新在前）。"""
    from .session import list_sessions

    ui.render_sessions(list(reversed(list_sessions())))


def _resolve_session(ui, target: str | None) -> str | None:
    """把 /continue 参数解析为会话 ID：缺省=最新；支持 ID 前缀或序号。"""
    from .session import list_sessions

    sessions = list(reversed(list_sessions()))  # 最新在前
    if not sessions:
        ui.error("暂无会话历史。")
        return None
    if target is None:
        return sessions[0].id
    for s in sessions:
        if s.id == target or s.id.startswith(target):
            return s.id
    if target.isdigit():
        idx = int(target)
        if 1 <= idx <= len(sessions):
            return sessions[idx - 1].id
    ui.error(f"未找到会话：{target}（用 /sessions 查看列表）")
    return None


def _resolve_skill_invocation(line: str, skills):
    """把 `/skill-name [附加提示]` 解析为 (skill, 附加提示)；非 skill 调用返回 None。

    规则：去掉 / 后的第一个空白分隔 token 若命中某个已注册 skill 名，即为 skill 调用，
    其余文本作为附加提示；否则返回 None，交由内置命令处理。
    """
    if not line.startswith("/"):
        return None
    body = line[1:]
    token = body.split(None, 1)[0] if body.strip() else ""
    if not token:
        return None
    skill = skills.get(token)
    if skill is None:
        return None
    rest = body[len(token):].strip()
    return skill, rest


def _list_skills(ui, agent) -> None:
    """列出全部可用 skill（内置 + 自定义）。"""
    ui.render_skills(agent.ctx.skills.list())


def _show_skill(ui, agent, name: str) -> None:
    """展示单个 skill 的用途与执行指引；名称为空时回退为列表。"""
    skills = agent.ctx.skills
    if not name:
        ui.render_skills(skills.list())
        return
    skill = skills.get(name)
    if skill is None:
        ui.error(f"skill 不存在：{name}（输入 /skills 查看可用 skill）")
        return
    ui.render_skill(skill)


if __name__ == "__main__":
    raise SystemExit(main())
