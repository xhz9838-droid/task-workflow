# -*- coding: utf-8 -*-
"""P11 Phase 2 — Runner：Claude Code 子进程启动与生命周期管理。

职责（P11 §四.1）：
    - 启动 Claude Code CLI，传入 Skill 工作流入口与项目/任务参数
    - 记录 PID、启动时间、工作目录、命令行
    - 捕获 stdout/stderr
    - 支持正常退出 / 超时终止 / 用户取消
    - 任务级锁防重复启动
    - 恢复时识别已有进程

Windows 要求：
    - subprocess + UTF-8（errors=replace）
    - CREATE_NEW_PROCESS_GROUP（独立进程组，便于整树终止）
    - 进程残留处理

安全：命令行与日志**不含** API Key / Token / 密码。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from typing import Callable, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from .exceptions import AgentStartError, AgentTimeoutError, DuplicateExecutionError, TaskLockError
    from .models import AgentRun, AgentState
    from .state_manager import StateManager
except ImportError:
    from exceptions import AgentStartError, AgentTimeoutError, DuplicateExecutionError, TaskLockError  # type: ignore
    from models import AgentRun, AgentState  # type: ignore
    from state_manager import StateManager  # type: ignore

IS_WINDOWS = os.name == "nt"
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def default_claude_cmd() -> str:
    """定位 Claude Code CLI。按实测：全局 npm 安装的 `claude`。"""
    for cand in ("claude", "claude.cmd", "claude.exe"):
        from shutil import which

        p = which(cand)
        if p:
            return p
    return "claude"


def default_claude_flags() -> list[str]:
    """无头启动的受控参数（docs/execution/integration-plan.md 约定形态）。

    - --verbose：`--output-format stream-json` 的硬性要求，缺则 CLI 直接报错退出
    - --permission-mode acceptEdits + 最小 allowedTools：无头运行不卡在授权提示，
      且不放开 Bash 等任意执行面
    可用环境变量 CLAUDE_RUNNER_FLAGS 覆盖（空格分隔，引号内为完整参数值），
    例如真实开发任务需要更宽工具白名单时。
    """
    raw = os.environ.get("CLAUDE_RUNNER_FLAGS", "").strip()
    if raw:
        import shlex

        return shlex.split(raw)
    return [
        "--permission-mode", "acceptEdits",
        "--allowedTools", "mcp__human-decision",
    ]


class AgentRunner:
    """子 Agent 进程管理。一个 task_id 同时只允许一个有效实例。"""

    def __init__(self, state: StateManager, *, claude_cmd: str | None = None, logger: Callable[[str], None] | None = None):
        self.state = state
        self.claude_cmd = claude_cmd or default_claude_cmd()
        self._log = logger or (lambda m: None)
        self._proc: Optional[subprocess.Popen] = None
        self._agent_run_id: Optional[int] = None
        self._project_key: Optional[str] = None
        self._task_id: Optional[str] = None
        self._cancel = threading.Event()

    # ------------------------------------------------------- 启动
    def start(
        self,
        *,
        project_key: str,
        task_id: str,
        prompt: str,
        workdir: str,
        execution_id: int,
        agent_name: str = "main",
        session_id: str | None = None,
        timeout_seconds: int = 1800,
        extra_args: list[str] | None = None,
    ) -> AgentRun:
        """启动一次 Agent 运行。返回 AgentRun（含 PID）。"""
        # 任务锁：同一 task_id 不允许并发
        my_pid = os.getpid()
        if not self.state.acquire_lock(project_key, task_id, my_pid, owner=agent_name):
            raise TaskLockError(
                f"任务 {project_key}/{task_id} 已有运行实例，禁止重复启动。"
                f" 用 --resume 恢复，或等待其结束后重试。"
            )

        # prompt 经 stdin 传入：argv 传多行 prompt 会被 Windows cmd.exe（.cmd 垫片）
        # 按换行截断，实测 agent 只收到第一行甚至无输出（真实缺陷，2026-11-17 验收发现）。
        cmd = [self.claude_cmd, "-p", "--output-format", "stream-json", "--verbose"]
        cmd += default_claude_flags()
        if session_id:
            cmd += ["--resume", session_id]
        if extra_args:
            cmd += list(extra_args)

        self._project_key = project_key
        self._task_id = task_id

        run = AgentRun(
            execution_id=execution_id,
            agent_name=agent_name,
            status=AgentState.STARTING,
            cmd=" ".join(cmd[:4]) + " …(prompt 经 stdin 传入)",
            workdir=workdir,
        )
        self._agent_run_id = self.state.create_agent_run(run)
        self.state.log_event(execution_id, "agent_starting", {"agent": agent_name, "workdir": workdir})

        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        # 不把任何凭据写入命令行；敏感项只经环境变量由上层注入
        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=workdir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW if IS_WINDOWS else 0,
            )
            if self._proc.stdin:
                self._proc.stdin.write(prompt)
                self._proc.stdin.close()
        except OSError as e:
            run.status = AgentState.FAILED
            run.error_message = f"启动失败: {e}"
            self.state.update_agent_run(self._agent_run_id, status=run.status, error_message=run.error_message)
            self.state.release_lock(project_key, task_id)
            raise AgentStartError(f"Agent 启动失败: {e}")

        run.pid = self._proc.pid
        run.status = AgentState.RUNNING
        import datetime

        run.started_at = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        self.state.update_agent_run(
            self._agent_run_id,
            pid=run.pid,
            status=run.status,
            started_at=run.started_at,
            last_output_at=run.started_at,
        )
        self.state.log_event(execution_id, "agent_running", {"agent": agent_name, "pid": run.pid})

        # 后台读输出（更新 last_output_at 用于 Output Activity 判定）
        self._start_output_pump(execution_id)
        return run

    def _start_output_pump(self, execution_id: int) -> None:
        """持续读 stdout/stderr，更新 last_output_at。**不**据此判定卡死。"""
        proc = self._proc
        if not proc:
            return

        def pump(stream, tag):
            try:
                for line in iter(stream.readline, ""):
                    if self._agent_run_id:
                        self.state.update_agent_run(self._agent_run_id, last_output_at=_iso_now())
                    self._log(f"[{tag}] {line.rstrip()[:200]}")
            except Exception:
                pass

        threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True).start()
        threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True).start()

    # ------------------------------------------------------- 等待 / 取消 / 超时
    def wait(self, timeout_seconds: int | None = None) -> tuple[AgentState, int]:
        """等待子进程结束。返回 (终态, exit_code)。"""
        if not self._proc:
            raise AgentStartError("无运行中的进程")
        try:
            code = self._proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            self.terminate(reason="timeout")
            raise AgentTimeoutError(f"Agent 超时（>{timeout_seconds}s）")
        state = AgentState.SUCCEEDED if code == 0 else AgentState.FAILED
        self._finalize(state, code)
        return state, code

    def cancel(self) -> None:
        """用户取消。"""
        self._cancel.set()
        self.terminate(reason="cancelled")

    def terminate(self, reason: str = "") -> None:
        """终止进程（Windows 整树终止）。"""
        if not self._proc:
            return
        try:
            if IS_WINDOWS:
                self._proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
                time.sleep(0.5)
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self._proc.pid)],
                    capture_output=True,
                )
            else:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
        except Exception as e:
            self._log(f"terminate 异常（忽略）: {e}")

        code = self._proc.returncode if self._proc.returncode is not None else -1
        if reason == "timeout":
            self._finalize(AgentState.TIMEOUT, code)
        elif reason == "cancelled":
            self._finalize(AgentState.CANCELLED, code)
        else:
            self._finalize(AgentState.INTERRUPTED, code)

    def _finalize(self, state: AgentState, exit_code: int) -> None:
        import datetime

        fin = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        if self._agent_run_id:
            self.state.update_agent_run(
                self._agent_run_id,
                status=state,
                finished_at=fin,
                exit_code=exit_code,
                error_message=None if state == AgentState.SUCCEEDED else f"exit={exit_code}",
            )
            self.state.log_event(
                self._agent_run_id,
                "agent_finished",
                {"state": state.value, "exit_code": exit_code},
            )
        # 释放任务锁（一次运行一锁，终态即释放）
        self._release_task_lock()

    def _release_task_lock(self) -> None:
        """释放本次运行持有的任务锁（需要知道 project/task）。"""
        proj = getattr(self, "_project_key", None)
        task = getattr(self, "_task_id", None)
        if proj and task:
            self.state.release_lock(proj, task)


def _iso_now() -> str:
    import datetime

    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------- CLI 入口（P11.1）
# 统一 argparse/退出码/输出见 cli.py；此处仅转发，不重复实现业务逻辑。
if __name__ == "__main__":
    try:
        from cli import runner_main
    except ImportError:
        from .cli import runner_main  # type: ignore
    raise SystemExit(runner_main(sys.argv[1:]))
