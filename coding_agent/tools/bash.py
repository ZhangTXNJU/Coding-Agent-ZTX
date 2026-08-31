"""命令执行工具：bash + 危险命令识别。

危险命令在真正执行前被拦截（除非 auto_approve 或 confirm 放行）。
"""
from __future__ import annotations

import os
import re
import subprocess

from ..errors import ToolError
from .registry import Tool, ToolContext

def dangerous_reason(command: str) -> str | None:
    """返回危险命令的原因描述；安全命令返回 None。"""
    c = command.strip()
    # rm -rf 的各种写法（rm -rf / rm -fr / rm -r -f / rm --recursive --force）
    if re.search(r"\brm\b", c) and re.search(r"(^|\s)-[a-z]*r", c) and re.search(r"(^|\s)-[a-z]*f", c):
        return "递归强制删除（rm -rf）"
    if re.search(r"\bgit\s+push\b[^\n]*(--force|--force-with-lease)", c):
        return "强制推送（git push --force）"
    if re.search(r"\bdd\b[^\n]*of=/dev/", c):
        return "直接写设备（dd of=/dev/...）"
    if re.search(r"\bmkfs(\.[a-z0-9]+)?\b", c):
        return "格式化文件系统（mkfs）"
    if re.search(r":\(\)\s*\{.*\};\s*:", c):
        return "fork 炸弹"
    if re.search(r"\bsudo\s+rm\b", c):
        return "sudo 删除"
    if re.search(r"\b(shutdown|reboot|halt|poweroff)\b", c):
        return "关机/重启"
    if re.search(r">\s*/dev/sd[a-z]", c):
        return "写裸设备"
    if re.search(r"\bchmod\s+-R\s+777\s+/", c):
        return "递归开放 777 权限"
    return None


# 非交互执行：关闭 stdin，并封死 git/pip/apt 等工具的交互提示
_NONINTERACTIVE_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "DEBIAN_FRONTEND": "noninteractive",
    "PYTHONUNBUFFERED": "1",
    "PIP_NO_INPUT": "1",
}


def run_bash(args: dict, ctx: ToolContext) -> str:
    command = args["command"]
    reason = dangerous_reason(command)
    if reason is not None and not ctx.auto_approve:
        if ctx.confirm is None:
            raise ToolError(f"危险命令需确认（{reason}），已拒绝：{command}")
        if not ctx.confirm(command):
            raise ToolError(f"用户取消了危险命令：{command}")

    timeout = args.get("timeout") or ctx.command_timeout
    env = {**os.environ, **_NONINTERACTIVE_ENV}
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=ctx.workdir,
            timeout=timeout,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"命令超时（>{timeout}s）：{command}") from exc
    except OSError as exc:
        raise ToolError(f"命令执行失败：{exc}") from exc

    parts = [f"exit_code: {proc.returncode}"]
    if proc.stdout:
        parts.append("stdout:\n" + proc.stdout.rstrip())
    if proc.stderr:
        parts.append("stderr:\n" + proc.stderr.rstrip())
    return "\n".join(parts)


BASH = Tool(
    name="bash",
    description=(
        "在工作目录内非交互执行 shell 命令（stdin 已关闭），返回 stdout/stderr 与退出码；"
        "输出超长会被截断。需要交互输入的程序请改用非交互 flag（如 --yes / -y / --no-input）。"
        "破坏性命令需用户确认。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "description": "超时秒数（默认 120）"},
        },
        "required": ["command"],
    },
    handler=run_bash,
)
