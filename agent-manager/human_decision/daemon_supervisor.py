# -*- coding: utf-8 -*-
"""HITL daemon 监督进程（零管理员自启方案）。

职责：
    - 单实例保护（本进程锁：hitl-supervisor.lock）
    - 拉起并监护 cli.py daemon：异常退出后按退避间隔自动重启
    - 退出码 2（已有 daemon 实例）→ 等待后重试，不重复拉起
    - 运行日志：logs/hitl-supervisor.log（事件级）+ daemon 输出重定向 hitl-daemon.out.log

自启方式：HKCU Run 键（当前用户登录自启，无需管理员）：
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" ^
        /v hitl-daemon /t REG_SZ /d "pythonw.exe D:\WorkSpace\task-workflow\agent-manager\human_decision\daemon_supervisor.py" /f

注：Windows 计划任务需提升权限（本机 UAC 拒绝非提升注册），故用 Run 键 + 本监督进程
实现同等能力：开机自启 / 崩溃自愈 / 单实例 / 日志 / 与终端无关。
"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)  # agent-manager/
_ROOT = os.path.dirname(_PARENT)  # task-workflow/
_LOG_DIR = os.path.join(_PARENT, "logs")
_SUPERVISOR_LOG = os.path.join(_LOG_DIR, "hitl-supervisor.log")
_DAEMON_OUT = os.path.join(_LOG_DIR, "hitl-daemon.out.log")
_LOCK = os.path.join(_LOG_DIR, "hitl-supervisor.lock")

RESTART_BACKOFF_SECONDS = 10   # daemon 崩溃后重启间隔
BUSY_BACKOFF_SECONDS = 60      # 退出码 2（他实例在跑）时的重试间隔


def log(msg: str) -> None:
    os.makedirs(_LOG_DIR, exist_ok=True)
    line = f"{datetime.datetime.now().astimezone().isoformat(timespec='seconds')} {msg}\n"
    with open(_SUPERVISOR_LOG, "a", encoding="utf-8") as f:
        f.write(line)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def acquire_lock() -> bool:
    os.makedirs(_LOG_DIR, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            return True
        except FileExistsError:
            try:
                old = int((open(_LOCK, encoding="utf-8").read() or "0").strip() or "0")
            except (OSError, ValueError):
                old = 0
            if pid_alive(old):
                return False
            try:
                os.unlink(_LOCK)
            except OSError:
                return False
    return False


def main() -> int:
    if not acquire_lock():
        log(f"supervisor 已有实例，退出（pid={os.getpid()}）")
        return 2
    log(f"supervisor 启动（pid={os.getpid()}）")
    try:
        while True:
            cmd = [sys.executable, "-u", os.path.join(_HERE, "cli.py"), "daemon", "--interval", "3"]
            log("拉起 daemon: " + " ".join(cmd))
            try:
                with open(_DAEMON_OUT, "a", encoding="utf-8", errors="replace") as out:
                    rc = subprocess.call(
                        cmd, cwd=_ROOT, stdout=out, stderr=subprocess.STDOUT,
                    )
            except Exception as e:
                log(f"daemon 拉起失败: {e}")
                rc = -1
            if rc == 2:
                log("daemon 已有实例在运行（rc=2），等待重试")
                time.sleep(BUSY_BACKOFF_SECONDS)
            else:
                log(f"daemon 退出 rc={rc}，{RESTART_BACKOFF_SECONDS}s 后重启")
                time.sleep(RESTART_BACKOFF_SECONDS)
    finally:
        try:
            os.unlink(_LOCK)
        except OSError:
            pass
        log("supervisor 退出")


if __name__ == "__main__":
    sys.exit(main())
