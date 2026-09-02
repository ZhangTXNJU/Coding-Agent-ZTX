"""工具注册表：name → Tool（description/schema/handler）。

本模块不 import 任何具体工具，避免循环导入；工具在此定义、在 __init__.py 汇总注册。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..errors import ToolError
from ..skills import SkillRegistry

# 只读工具白名单：规划/需求阶段仅暴露这些（默认拒绝，新工具不会误入只读模式）。
# 读文件/列目录/搜索 + todo_write（todo 是内存规划状态，非文件写）+ ask_user（只读提问），
# 不含 bash 与任何写文件工具。
READ_ONLY_TOOL_NAMES = frozenset({"read_file", "list_dir", "glob", "grep", "todo_write", "ask_user"})


@dataclass
class ToolContext:
    """工具执行上下文（由 agent 主循环持有，跨工具调用共享可变状态）。"""

    workdir: Path = field(default_factory=Path.cwd)
    command_timeout: int = 120
    auto_approve: bool = False
    # 危险命令确认回调：返回 True 才放行。Phase 8 由 UI 注入（rich [y/N] 提示）。
    confirm: Callable[[str], bool] | None = None
    # 交互提问回调（ask_user 工具）：接收问题列表，返回用户回答文本。由 UI 注入。
    ask_user: Callable[[list], str] | None = None
    # todo_write 的状态载体（跨步持久，直到会话结束）。
    todos: list = field(default_factory=list)
    # use_skill 的 skill 来源（内置 + 自定义）。
    skills: SkillRegistry = field(default_factory=SkillRegistry)
    # 子 agent 委托回调（由 agent 主循环注入）：接收自包含 prompt，返回子 agent 最终结论。
    spawn_subagent: Callable[[str], str] | None = None
    # 只读模式：True 时主循环把工具集裁剪为只读白名单（禁写文件/bash）。
    # 由只读 skill 触发（use_skill 或 run(skill=...)），跨步骤持久、run 结束复位。
    read_only: bool = False


@dataclass
class Tool:
    """一个可被模型调用的工具。"""

    name: str
    description: str
    parameters: dict  # JSON Schema（object）
    handler: Callable[[dict, ToolContext], str]

    def to_openai(self) -> dict:
        """导出为 OpenAI function calling 的工具定义。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """name → Tool 的注册与分发。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册：{tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"未知工具：{name!r}") from exc

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return list(self._tools)

    def to_openai_tools(self) -> list[dict]:
        return [t.to_openai() for t in self._tools.values()]

    def without(self, name: str) -> "ToolRegistry":
        """返回去掉指定工具的副本（用于子 agent 禁嵌套）。"""
        reg = ToolRegistry()
        for n, tool in self._tools.items():
            if n != name:
                reg.register(tool)
        return reg

    def read_only(self) -> "ToolRegistry":
        """返回只含只读工具白名单的副本（规划/需求阶段：可读不可改）。"""
        reg = ToolRegistry()
        for n, tool in self._tools.items():
            if n in READ_ONLY_TOOL_NAMES:
                reg.register(tool)
        return reg

    def run(self, name: str, arguments: dict, ctx: ToolContext) -> str:
        """执行工具并返回结果文本；执行错误统一包装为 ToolError。"""
        tool = self.get(name)
        try:
            return tool.handler(arguments, ctx)
        except ToolError:
            raise
        except Exception as exc:  # 工具内部 bug 兜底，避免循环崩溃
            raise ToolError(f"工具 {name} 执行失败: {exc}") from exc
