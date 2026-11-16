# -*- coding: utf-8 -*-
"""P11 Phase 2 — Monitor：运行监控。

四个概念严格区分（P11 §四.2）：
    1. Process Alive    — 操作系统进程存活（psutil/ctypes 查 PID）
    2. Heartbeat        — 管理器确认 Agent 仍在正常执行或报告进度
    3. Output Activity  — 最近是否有输出（last_output_at）
    4. Workflow Progress— 工作流是否推进到下一阶段

**关键**：Claude Code 思考时可能长时间无输出，**不得**仅凭 stdout 静默就杀进程。
综合判断：进程状态 + 阶段超时 + 输出活动 + 任务预算。

无可靠 Agent 内部心跳源时，heartbeat 标 `unavailable`，**不伪造**。
"""
from __future__ import annotations

import datetime
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from .models import AgentState
except ImportError:
    from models import AgentState  # type: ignore


def _iso_now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def pid_alive(pid: int) -> bool:
    """Process Alive —— 跨平台 PID 存活检查。"""
    if not pid or pid <= 0:
        return False
    try:
        import psutil  # type: ignore

        return psutil.pid_exists(pid)
    except ImportError:
        pass
    try:
        if os.name == "nt":
            import ctypes

            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(0x1000, False, int(pid))
            if h:
                k32.CloseHandle(h)
                return True
            return False
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def process_start_time(pid: int) -> Optional[float]:
    """进程启动时间（用于 PID 重用误判防护）。"""
    try:
        import psutil  # type: ignore

        return psutil.Process(pid).create_time()
    except Exception:
        return None


@dataclass
class HealthSnapshot:
    """一次监控采样 —— 四个维度分别记录，不混为一谈"""

    pid: Optional[int]
    process_alive: bool
    heartbeat: str  # "ok" | "unavailable" | "stale"
    last_output_at: Optional[str]
    output_idle_seconds: float
    stage: str
    workflow_progress: str
    elapsed_seconds: float
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "process_alive": self.process_alive,
            "heartbeat": self.heartbeat,
            "last_output_at": self.last_output_at,
            "output_idle_seconds": round(self.output_idle_seconds, 1),
            "stage": self.stage,
            "workflow_progress": self.workflow_progress,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "warnings": self.warnings,
        }


class Monitor:
    """进程/输出/阶段监控。**输出静默只告警不杀**（P11 §十 注意事项）。"""

    def __init__(
        self,
        *,
        poll_interval_seconds: float = 5.0,
        heartbeat_timeout_seconds: float = 300.0,
        default_task_timeout_seconds: float = 1800.0,
        output_idle_warning_seconds: float = 300.0,
    ):
        self.poll = poll_interval_seconds
        self.heartbeat_timeout = heartbeat_timeout_seconds
        self.task_timeout = default_task_timeout_seconds
        self.output_idle_warning = output_idle_warning_seconds

    def snapshot(
        self,
        *,
        pid: Optional[int],
        started_at: Optional[str],
        last_output_at: Optional[str],
        stage: str = "",
        workflow_progress: str = "",
        has_heartbeat: bool = False,
        heartbeat_at: Optional[str] = None,
    ) -> HealthSnapshot:
        now = datetime.datetime.now().astimezone()
        alive = pid_alive(pid) if pid else False

        # Output Activity：距上次输出的秒数
        idle = 0.0
        if last_output_at:
            try:
                idle = (now - datetime.datetime.fromisoformat(last_output_at)).total_seconds()
            except Exception:
                idle = 0.0

        # Heartbeat：无可靠源 → unavailable（不伪造）
        if not has_heartbeat:
            hb = "unavailable"
        elif heartbeat_at:
            try:
                hb_idle = (now - datetime.datetime.fromisoformat(heartbeat_at)).total_seconds()
                hb = "stale" if hb_idle > self.heartbeat_timeout else "ok"
            except Exception:
                hb = "unavailable"
        else:
            hb = "unavailable"

        elapsed = 0.0
        if started_at:
            try:
                elapsed = (now - datetime.datetime.fromisoformat(started_at)).total_seconds()
            except Exception:
                elapsed = 0.0

        warnings: list[str] = []
        # 输出静默 → 仅告警，**不**触发杀进程
        if idle > self.output_idle_warning:
            warnings.append(
                f"输出静默 {int(idle)}s（>{int(self.output_idle_warning)}s）："
                f"可能在思考中，不据此判定卡死"
            )
        if elapsed > self.task_timeout:
            warnings.append(f"任务总耗时 {int(elapsed)}s 超预算 {int(self.task_timeout)}s")

        return HealthSnapshot(
            pid=pid,
            process_alive=alive,
            heartbeat=hb,
            last_output_at=last_output_at,
            output_idle_seconds=idle,
            stage=stage,
            workflow_progress=workflow_progress,
            elapsed_seconds=elapsed,
            warnings=warnings,
        )

    def should_kill(
        self,
        snap: HealthSnapshot,
        *,
        stage_timeout_seconds: Optional[float] = None,
        stage_started_at: Optional[str] = None,
    ) -> tuple[bool, str]:
        """判定是否应终止进程。

        **仅**以下情况返回 True：
            1. 进程已不存在 → 不需杀，返回 False（由上层处理退出）
            2. 阶段超时（stage_timeout）且进程仍在 → 杀
            3. 任务总超时（task_timeout）且进程仍在 → 杀

        输出静默**永不**单独触发杀进程。
        """
        if not snap.process_alive:
            return False, "进程已退出，无需终止"

        if stage_timeout_seconds and stage_started_at:
            try:
                s_started = datetime.datetime.fromisoformat(stage_started_at)
                s_elapsed = (datetime.datetime.now().astimezone() - s_started).total_seconds()
                if s_elapsed > stage_timeout_seconds:
                    return True, f"阶段 [{snap.stage}] 超时 {int(s_elapsed)}s > {int(stage_timeout_seconds)}s"
            except Exception:
                pass

        if snap.elapsed_seconds > self.task_timeout:
            return True, f"任务总超时 {int(snap.elapsed_seconds)}s > {int(self.task_timeout)}s"

        return False, ""

    def watch(
        self,
        *,
        pid: Optional[int],
        started_at: Optional[str],
        last_output_at: Optional[str],
        stage: str = "",
        is_terminal: callable = None,
        max_seconds: Optional[float] = None,
        on_warning: callable = None,
    ) -> HealthSnapshot:
        """轮询直到终态或超时。返回最后快照。"""
        deadline = time.time() + (max_seconds or self.task_timeout)
        last = None
        while time.time() < deadline:
            last = self.snapshot(
                pid=pid,
                started_at=started_at,
                last_output_at=last_output_at,
                stage=stage,
            )
            if is_terminal and is_terminal():
                return last
            if not last.process_alive:
                return last
            for w in last.warnings:
                if on_warning:
                    on_warning(w)
            time.sleep(self.poll)
        return last or self.snapshot(pid=pid, started_at=started_at, last_output_at=last_output_at, stage=stage)


# --------------------------------------------------------------- CLI 入口（P11.1）
if __name__ == "__main__":
    try:
        from cli import monitor_main
    except ImportError:
        from .cli import monitor_main  # type: ignore
    raise SystemExit(monitor_main(sys.argv[1:]))
