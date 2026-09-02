"""命令执行工具：bash + 危险命令识别。

危险命令在真正执行前被拦截（除非 auto_approve 或 confirm 放行）。
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
import threading

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

# 后台任务注册表（进程级全局）：task_id -> (Popen, 输出临时文件路径)。
# 用线程锁保护：主 agent 与子 agent 同进程共享此注册表，且为后续并行工具执行预留并发安全。
_BG_TASKS: dict[str, tuple[subprocess.Popen, str]] = {}
_BG_SEQ = 0
_BG_LOCK = threading.Lock()

# 后台任务输出回传的最大字符数（保护上下文）。
_BG_OUTPUT_MAX_CHARS = 4000


def run_bash(args: dict, ctx: ToolContext) -> str:
    command = args["command"]
    reason = dangerous_reason(command)
    if reason is not None and not ctx.auto_approve:
        if ctx.confirm is None:
            raise ToolError(f"危险命令需确认（{reason}），已拒绝：{command}")
        if not ctx.confirm(command):
            raise ToolError(f"用户取消了危险命令：{command}")

    if args.get("background"):
        return _run_bash_background(command, ctx)

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


def _run_bash_background(command: str, ctx: ToolContext) -> str:
    """后台启动命令并立即返回任务号，用 bash_wait 稍后查询结果。

    关键点：
      - 输出重定向到临时文件而非 stdout=PIPE——若用 PIPE 且长时间不读取，输出写满
        管道缓冲会让子进程卡死在 write（经典死锁）。
      - start_new_session=True 让子进程脱离当前进程组，不随 agent 中断被误杀。
      - 危险命令确认在 run_bash 里已前置完成，这里不再重复。
    """
    global _BG_SEQ
    env = {**os.environ, **_NONINTERACTIVE_ENV}
    out_f = tempfile.NamedTemporaryFile(mode="w", prefix="bg_", suffix=".log", delete=False)
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=ctx.workdir,
            stdout=out_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    finally:
        out_f.close()  # 子进程持有 dup 后的 fd，此处可安全关闭我们这份
    with _BG_LOCK:
        _BG_SEQ += 1
        task_id = str(_BG_SEQ)
        _BG_TASKS[task_id] = (proc, out_f.name)
    return (
        f"已后台启动任务 #{task_id}：{command}\n"
        f"命令在后台运行，本工具已立即返回。稍后用 bash_wait(task_id={task_id!r}) 查询结果。"
    )


def _read_output(path: str, max_chars: int = _BG_OUTPUT_MAX_CHARS) -> str:
    """读取后台任务输出文件；末尾截断以保护上下文。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""
    return text[-max_chars:] if len(text) > max_chars else text


def wait_bash(args: dict, ctx: ToolContext) -> str:
    """查询/等待一个后台任务：阻塞直到结束或超时。"""
    task_id = str(args["task_id"])
    timeout = args.get("timeout") or ctx.command_timeout
    with _BG_LOCK:
        item = _BG_TASKS.get(task_id)
    if item is None:
        raise ToolError(f"未知或已完成的后台任务：{task_id}")
    proc, out_path = item
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # 超时只表示本次没等到，任务继续在后台跑，模型可稍后再次查询
        return (
            f"任务 #{task_id} 仍在运行中（已等待 {timeout}s 尚未结束）。"
            f"稍后可再次调用 bash_wait 查询。"
        )
    with _BG_LOCK:
        _BG_TASKS.pop(task_id, None)
    output = _read_output(out_path)
    try:
        os.unlink(out_path)
    except OSError:
        pass
    if not output.strip():
        output = "（无输出）"
    return f"任务 #{task_id} 已结束，exit_code: {proc.returncode}\n{output}"


def cleanup_background_tasks() -> None:
    """结束会话时清理所有仍在运行的后台任务（kill 进程组并删除临时文件）。"""
    with _BG_LOCK:
        items = list(_BG_TASKS.items())
        _BG_TASKS.clear()
    for _, (proc, out_path) in items:
        if proc.poll() is None:  # 仍在运行才 kill
            try:
                # start_new_session 使子进程 pgid == pid，按进程组杀可连带杀掉其子孙进程
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
        try:
            os.unlink(out_path)
        except OSError:
            pass


BASH = Tool(
    name="bash",
    description=(
        "在工作目录内非交互执行 shell 命令（stdin 已关闭），返回 stdout/stderr 与退出码；"
        "输出超长会被截断。需要交互输入的程序请改用非交互 flag（如 --yes / -y / --no-input）。"
        "破坏性命令需用户确认。设置 background=true 可把测试/安装等长命令放到后台运行并立即返回任务号，"
        "配合 bash_wait 查询结果。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "description": "超时秒数（默认 120）"},
            "background": {
                "type": "boolean",
                "description": "true 时后台运行并立即返回任务号，稍后用 bash_wait 查询结果（适合测试/安装等长命令）",
            },
        },
        "required": ["command"],
    },
    handler=run_bash,
)


BASH_WAIT = Tool(
    name="bash_wait",
    description=(
        "查询或等待一个后台任务（由 bash 的 background=true 启动）的结果。"
        "会阻塞直到任务结束或超时；超时只表示本次没等到，任务仍在后台运行，可稍后再次调用。"
        "任务结束后结果与临时文件会被自动清理，再次查询会报错。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "后台任务编号（bash 返回的任务号）"},
            "timeout": {"type": "integer", "description": "最长等待秒数（默认 120）"},
        },
        "required": ["task_id"],
    },
    handler=wait_bash,
)
