"""agent 主循环：决策 → 解析 → 执行 → 回传 → 终止。

这是项目的核心闭环。终止条件：
  1. 模型返回无 tool_calls 的最终回答（finish_reason 任意）
  2. 达到 max_steps（MaxStepsExceeded）
  3. 连续工具调用失败达到 max_failures（MaxFailuresExceeded）
"""
from __future__ import annotations

import sys
from typing import Callable

from .config import AgentConfig
from .errors import LLMError, MaxFailuresExceeded, MaxStepsExceeded, ParsingError, ToolError
from .llm.client import ChatResponse, LLMClient, ToolCall
from .messages import Conversation
from .parsing import parse_tool_arguments
from .tools import ToolContext, ToolRegistry

SYSTEM_PROMPT = (
    "你是一个本地编程智能体（coding agent），在用户的工作目录里自主完成任务。\n"
    "你可以调用工具来读写文件、搜索代码、执行 shell 命令、维护任务清单。\n"
    "工作原则：\n"
    "1. 动手前先用 read_file / list_dir / grep 了解现状，不要凭空假设。\n"
    "2. 修改用 edit_file（精准替换）；新建文件用 write_file；批量改动用 apply_patch。\n"
    "3. 每次改完用 bash 运行测试或命令验证结果，根据输出决定下一步。\n"
    "4. 复杂任务先用 todo_write 拆解成步骤。\n"
    "5. 全部完成后，用一句话简洁总结你做了什么、如何验证的。"
)


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
        verbose: bool = False,
    ) -> None:
        self.config = config
        self.client = client
        self.registry = registry
        self.conversation = conversation
        self.ctx = ctx
        self.on_text = on_text
        self.verbose = verbose

    def run(self, task: str) -> str:
        """执行一个任务，返回模型的最终回答。"""
        self.conversation.add_user(task)
        consecutive_failures = 0

        for _step in range(self.config.max_steps):
            resp = self.client.chat(
                self.conversation.to_openai(),
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
                self.conversation.add_tool(tc.id, result, name=tc.name)

        raise MaxStepsExceeded(f"达到最大步数 {self.config.max_steps}，任务未完成")

    def _execute_tool(self, tc: ToolCall) -> tuple[str, bool]:
        """执行单个工具调用，返回 (结果文本, 是否成功)。"""
        try:
            args = parse_tool_arguments(tc.arguments)
        except ParsingError as exc:
            return f"错误：{exc}", False

        if self.verbose:
            print(f"→ 调用工具 {tc.name}({args})", file=sys.stderr)

        try:
            result = self.registry.run(tc.name, args, self.ctx)
        except ToolError as exc:
            return f"错误：{exc}", False
        except Exception as exc:  # 兜底，任何异常都回传而非崩溃
            return f"错误：{exc}", False

        if self.verbose:
            print(f"← 结果：{result[:200]}", file=sys.stderr)
        return result, True
