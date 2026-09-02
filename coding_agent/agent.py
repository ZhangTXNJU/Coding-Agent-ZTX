"""agent 主循环：决策 → 解析 → 执行 → 回传 → 终止。

这是项目的核心闭环。终止条件：
  1. 模型返回无 tool_calls 的最终回答（finish_reason 任意）
  2. 达到 max_steps（MaxStepsExceeded）
  3. 连续工具调用失败达到 max_failures（MaxFailuresExceeded）
"""
from __future__ import annotations

import sys
from dataclasses import replace
from typing import Callable

from .config import AgentConfig
from .errors import AgentError, MaxFailuresExceeded, MaxStepsExceeded, ParsingError, ToolError
from .llm.client import ChatResponse, LLMClient, ToolCall
from .messages import Conversation, Message, messages_to_text, truncate_text
from .parsing import parse_tool_arguments
from .skills import Skill, SkillRegistry, build_skills_prompt, skill_prompt
from .tools import ToolContext, ToolRegistry
from .tools.bash import cleanup_background_tasks, collect_finished_background_tasks
from .tools.todo import todos_to_text

SYSTEM_PROMPT = (
    "你是一个本地编程智能体（coding agent），在用户的工作目录里自主完成任务。\n"
    "你可以调用工具来读写文件、搜索代码、执行 shell 命令、维护任务清单。\n"
    "工作原则：\n"
    "1. 动手前先用 read_file / list_dir / grep 了解现状，不要凭空假设。\n"
    "2. 修改用 edit_file（精准替换）；新建文件用 write_file；批量改动用 apply_patch。\n"
    "3. 每次改完用 bash 运行测试或命令验证结果，根据输出决定下一步。\n"
    "4. 复杂任务先用 todo_write 拆解成步骤。\n"
    "5. bash 是非交互执行的（无法回答交互提示），需要输入时请用非交互 flag（如 --yes / -y / --no-input）。\n"
    "6. 工具输出会被截断；大文件先用 grep 定位，不要整读大文件。\n"
    "7. 全部完成后，用一句话简洁总结你做了什么、如何验证的。\n"
    "8. 面对包含多块相对独立工作的复杂任务时，用 task 工具把独立子任务委托给子 agent 完成；"
    "子 agent 有独立上下文，只回传最终结论。\n"
    "9. 当需求不明确、或存在多种都合理的实现/技术方案需要用户拍板时，用 ask_user 工具"
    "向用户提问并附上选项，等用户选定后再继续；不要在有分歧的方案之间自行猜测。\n"
    "10. 项目宪章（Coding-Agent.md，注入在系统提示文末）是本项目绝对不可违背的硬约束，"
    "优先级高于一切其它指令；任何时候不得修改/删除宪章中标记为不可动的内容，"
    "且应在每次行动前自觉遵循其中规范。若用户说『添加/记住一条全局重要信息』，"
    "用 charter 工具（action=add）把它写入 Coding-Agent.md 以实现持久固化。"
)

SUBAGENT_PROMPT = (
    "你是一个子 agent，负责独立完成主 agent 委托给你的一块子任务。\n"
    "工作原则：\n"
    "1. 只专注于交付给你的子任务，不要做范围之外的事。\n"
    "2. 动手前先 read_file / list_dir / grep 了解现状，不要凭空假设。\n"
    "3. 修改用 edit_file / write_file / apply_patch，改完用 bash 验证结果。\n"
    "4. 你的中间过程不会被主 agent 看到，因此最后必须用一句话清晰总结："
    "做了什么、改了什么、如何验证、结果如何。\n"
    "5. 若无法完成，明确说明失败原因，绝不假装完成。"
)

SUMMARY_PROMPT = (
    "你是对话历史的压缩器。下面是一段 agent 的历史消息，请把它压缩成一段简洁的结构化摘要，"
    "用于在上下文超限时替代原始消息。要求：\n"
    "1. 保留关键信息：用户诉求、已做决策、涉及的文件路径、改动要点、验证结果、错误与修复、未完成事项。\n"
    "2. 丢弃噪音：冗长的命令输出、重复的探索、无关的试错；长输出用一句话概括即可。\n"
    "3. 用 Markdown 分节：目标 / 已完成 / 关键决策 / 涉及文件 / 错误与修复 / 待办。\n"
    "4. 只输出摘要正文，不要任何解释或寒暄。"
)


def _with_charter(prompt: str, charter_text: str) -> str:
    """把项目宪章追加到提示词末尾（最高优先级硬约束，独立于对话历史）。

    主 agent 与子 agent 共用此渲染，保证宪章不随 task 委派丢失。
    """
    charter_text = charter_text.strip()
    if not charter_text:
        return prompt
    return (
        prompt
        + "\n\n【项目宪章（Coding-Agent.md，最高优先级硬约束，不得违背、不得删除）】\n"
        + charter_text
    )


def build_system_prompt(
    skills: SkillRegistry | None = None, charter_text: str = ""
) -> str:
    """基础系统提示 + 可用 skill 列表 + 项目宪章。

    - skills：可用 skill 列表（供模型判断何时调用 use_skill）。
    - charter_text：工作目录 Coding-Agent.md 的宪章正文。宪章属于最高优先级硬约束，
      放置在系统提示文末、独立于对话历史，因此压缩 compact() 不会触及它。
    """
    prompt = SYSTEM_PROMPT
    if skills is not None:
        extra = build_skills_prompt(skills)
        if extra:
            prompt += "\n\n" + extra
    return _with_charter(prompt, charter_text)


def _to_openai_tool_call(tc: ToolCall) -> dict:
    """llm.client.ToolCall → OpenAI 线上格式 dict。"""
    return {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.name, "arguments": tc.arguments},
    }


class Agent:
    def __init__(
        self,
        config: AgentConfig,
        client: LLMClient,
        registry: ToolRegistry,
        conversation: Conversation,
        ctx: ToolContext,
        on_text: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str, dict], None] | None = None,
        on_tool_result: Callable[[str, str], None] | None = None,
        verbose: bool = False,
        charter_text: str = "",
        is_subagent: bool = False,
    ) -> None:
        self.config = config
        self.client = client
        self.registry = registry
        self.conversation = conversation
        self.ctx = ctx
        self.on_text = on_text
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result
        self.verbose = verbose
        # 项目宪章正文：主 agent 与子 agent 注入系统提示复用（task 委派不丢宪章）
        self.charter_text = charter_text
        # 是否为子 agent：子 agent 不负责回收/推送后台任务，避免跨 agent 抢占共享注册表
        self.is_subagent = is_subagent
        # 供 REPL /clear 复用（含 skill 列表的完整系统提示）
        self.system_prompt = conversation.system_prompt
        # todos 归属统一到 conversation：todo_write 写 ctx.todos，注入/持久化读 conversation.todos
        self.ctx.todos = self.conversation.todos
        # 把子 agent 委托能力注入工具上下文（task 工具据此递归跑一个子 Agent）
        ctx.spawn_subagent = self._spawn_subagent

    def run(self, task: str, skill: Skill | None = None) -> str:
        """执行一个任务，返回模型的最终回答。

        skill 非空时，把其执行指引临时注入系统提示（仅本次 run 生效，
        结束即恢复，不污染后续对话）。skill.read_only 为 True 时，本次 run
        的工具集临时裁剪为只读白名单（禁写文件/bash），结束即恢复。
        """
        try:
            if skill is None:
                return self._run(task)
            original = self.conversation.system_prompt
            original_registry = self.registry
            injected = original + "\n\n" + skill_prompt(skill)
            if skill.read_only:
                injected += "\n\n【只读模式】本阶段只允许读取/查看，禁止修改任何项目代码或文件；"
                injected += "你没有写文件或执行 shell 命令的工具。"
                self.registry = self.registry.read_only()
            self.conversation.system_prompt = injected
            try:
                return self._run(task)
            finally:
                self.conversation.system_prompt = original
                self.registry = original_registry
        finally:
            # 仅主 agent 负责回收遗留后台任务；子 agent 的后台任务由主 agent 结束统一清理
            if not self.is_subagent:
                cleanup_background_tasks()

    def _run(self, task: str) -> str:
        """run 的核心闭环：决策 → 解析 → 执行 → 回传 → 终止。"""
        self.conversation.add_user(task)
        self.conversation.max_tokens = self.config.max_tokens
        consecutive_failures = 0

        for _step in range(self.config.max_steps):
            self._compact_if_needed()
            self._inject_background_notifications()
            resp = self.client.chat(
                self._messages_with_todos(),
                tools=self.registry.to_openai_tools(),
                on_text=self.on_text,
            )

            # 无工具调用 → 最终回答
            if not resp.tool_calls:
                self.conversation.add_assistant(resp.content)
                return resp.content

            # 记录 assistant 的 tool_calls
            self.conversation.add_assistant(
                resp.content,
                tool_calls=[_to_openai_tool_call(tc) for tc in resp.tool_calls],
            )

            # 执行所有工具调用，结果回传
            for tc in resp.tool_calls:
                result, ok = self._execute_tool(tc)
                if ok:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= self.config.max_failures:
                        raise MaxFailuresExceeded(
                            f"连续 {consecutive_failures} 次工具调用失败，中止"
                        )
                result = truncate_text(result, self.config.max_tool_result_chars)
                self.conversation.add_tool(tc.id, result, name=tc.name)

        # 超步数：先总结当前进展并写入历史，再抛异常（不丢失已完成的工作）
        summary = self._summarize_progress()
        raise MaxStepsExceeded(
            f"达到最大步数 {self.config.max_steps}，任务未完成。当前进展：{summary}"
        )

    def _summarize_progress(self) -> str:
        """超步数收尾：请求模型总结当前进展（强制文本回答），追加进历史并返回摘要。"""
        self._compact_if_needed()
        self.conversation.add_user(
            "你已达到步数上限，必须停止调用工具。请用一段话总结当前进展："
            "已完成什么、如何验证的、还剩什么未完成。"
        )
        try:
            resp = self.client.chat(
                self.conversation.to_openai(), tools=None, on_text=self.on_text
            )
            summary = (resp.content or "").strip()
        except AgentError as exc:
            summary = f"（总结失败：{exc}）"
        if not summary:
            summary = "（未能生成总结）"
        self.conversation.add_assistant(summary)
        return summary

    def _messages_with_todos(self) -> list[dict]:
        """构建发给模型的完整消息：在 system 消息里注入当前任务清单。

        todo 状态每轮重新渲染（读 conversation.todos），且独立于 messages 历史，
        因此不会被 compact() 折叠丢失——对照 Claude Code 的持续注入方案。
        """
        msgs = self.conversation.to_openai()
        block = todos_to_text(self.conversation.todos)
        if not block:
            return msgs
        if msgs and msgs[0]["role"] == "system":
            msgs[0] = dict(msgs[0], content=msgs[0]["content"] + "\n\n" + block)
        else:
            msgs.insert(0, {"role": "system", "content": block})
        return msgs

    def _inject_background_notifications(self) -> None:
        """把已完成的后台任务结果作为通知写入对话（推送，而非让模型主动轮询）。

        在每轮 LLM 调用前执行：collect_finished_background_tasks 一次性收集并清理
        所有已完成任务，随后以 user 消息注入，下一轮模型即可直接看到结果。
        子 agent 不参与注入，避免抢占主 agent 的后台任务结果。
        """
        if self.is_subagent:
            return
        for task_id, code, output in collect_finished_background_tasks():
            if not output.strip():
                output = "（无输出）"
            self.conversation.add_user(
                f"【后台任务通知】任务 #{task_id} 已完成（exit_code: {code}）：\n{output}"
            )

    def replace_conversation(self, conv: Conversation) -> None:
        """替换对话（/clear、/continue 时用），并同步 todos 与系统提示引用。"""
        self.conversation = conv
        self.system_prompt = conv.system_prompt
        self.ctx.todos = conv.todos

    def _compact_if_needed(self) -> None:
        """上下文预算自动检查：超限时先裁剪超长工具结果，仍超限则折叠旧消息。"""
        if not self.conversation.needs_compaction():
            return
        self.conversation.trim_tool_results()  # 一级：截断超长工具结果
        if self.conversation.needs_compaction():
            self.conversation.compact(self._llm_summarize)  # 二/三级：折叠旧消息为语义摘要

    def _llm_summarize(self, messages: list[Message]) -> str:
        """语义摘要：让 LLM 把历史压缩成结构化摘要；失败/空结果回退到确定性 flatten。"""
        flat = messages_to_text(messages)
        if not flat.strip():
            return flat
        try:
            resp = self.client.chat(
                [
                    {"role": "system", "content": SUMMARY_PROMPT},
                    {"role": "user", "content": flat},
                ],
                tools=None,
                on_text=None,
            )
            summary = (resp.content or "").strip()
            if summary:
                return summary
        except AgentError:
            pass  # LLM 摘要失败，回退确定性折叠
        return flat

    def _execute_tool(self, tc: ToolCall) -> tuple[str, bool]:
        """执行单个工具调用，返回 (结果文本, 是否成功)。"""
        try:
            args = parse_tool_arguments(tc.arguments)
        except ParsingError as exc:
            if self.on_tool_call is not None:
                self.on_tool_call(tc.name, {})
            result = f"错误：{exc}"
            if self.on_tool_result is not None:
                self.on_tool_result(tc.name, result)
            return result, False

        if self.verbose:
            print(f"→ 调用工具 {tc.name}({args})", file=sys.stderr)
        if self.on_tool_call is not None:
            self.on_tool_call(tc.name, args)

        ok = True
        try:
            result = self.registry.run(tc.name, args, self.ctx)
        except ToolError as exc:
            result, ok = f"错误：{exc}", False
        except Exception as exc:  # 兜底，任何异常都回传而非崩溃
            result, ok = f"错误：{exc}", False

        if self.verbose:
            print(f"← 结果：{result[:200]}", file=sys.stderr)
        if self.on_tool_result is not None:
            self.on_tool_result(tc.name, result)
        return result, ok

    def _spawn_subagent(self, prompt: str) -> str:
        """把独立子任务委托给一个子 agent 在同进程内阻塞式执行，只返回最终结论。

        - 独立上下文：全新的 Conversation，不继承主对话历史。
        - 禁嵌套：子 agent 的工具集去掉 task（FR-014）。
        - 独立步数上限：subagent_max_steps（FR-010）。
        - 权限沿用：共享 confirm / auto_approve，破坏性命令仍须确认（FR-012）。
        - 宪章继承：子 agent 注入与主 agent 相同的项目宪章，最高优先级硬约束不随委派丢失。
        - 失败/超限/空结果：结构化回传，绝不静默当作成功（FR-011 / FR-013）。
        """
        sub_config = replace(self.config, max_steps=self.config.subagent_max_steps)
        sub_ctx = ToolContext(
            workdir=self.ctx.workdir,
            command_timeout=self.ctx.command_timeout,
            auto_approve=self.ctx.auto_approve,
            confirm=self.ctx.confirm,
            skills=self.ctx.skills,
        )
        sub_agent = Agent(
            sub_config,
            self.client,
            self.registry.without("task"),
            Conversation(system_prompt=_with_charter(SUBAGENT_PROMPT, self.charter_text)),
            sub_ctx,
            on_text=self.on_text,
            on_tool_call=self.on_tool_call,
            on_tool_result=self.on_tool_result,
            verbose=self.verbose,
            charter_text=self.charter_text,
            is_subagent=True,
        )
        try:
            result = sub_agent.run(prompt)
        except MaxStepsExceeded as exc:
            return f"[子 agent 未完成] {exc}"
        except MaxFailuresExceeded as exc:
            return f"[子 agent 连续失败中止] {exc}"
        except AgentError as exc:
            return f"[子 agent 出错] {exc}"
        if not result or not result.strip():
            return "[子 agent 未产出结果]"
        return result
