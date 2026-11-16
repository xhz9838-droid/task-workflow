# -*- coding: utf-8 -*-
"""P11 Phase 2 — State Manager：SQLite 状态持久化 + 任务锁 + 断点恢复。

表结构（P11 §六）：
    execution_runs      任务级执行
    agent_runs          子 Agent 运行
    execution_events    事件流（审计/恢复）
    verification_results 验证结果
    task_locks          任务级锁（防重复启动）
    pending_writes      待回写禅道事件（失败不丢）

设计要点：
    - 状态不只在内存，管理器异常退出后可恢复
    - 同一 task_id 只能有一个有效运行实例（任务锁 + 过期检查）
    - 恢复时核对 PID + 启动时间 + 工作目录，避免 PID 重用误判
    - 防并发写（SQLite 事务 + WAL）
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import threading
from typing import Any, Optional

import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from .models import AgentRun, AgentState, ExecutionRun, TaskState, VerifyCheck, VerifyStatus
except ImportError:
    from models import AgentRun, AgentState, ExecutionRun, TaskState, VerifyCheck, VerifyStatus  # type: ignore

DEFAULT_DB = os.path.join(_HERE, "logs", "agent_manager.db")
_LOCK_TTL_SECONDS = 3600  # 任务锁过期时间

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS execution_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_key       TEXT NOT NULL,
    task_id           TEXT NOT NULL,
    task_level        TEXT,
    workflow_status   TEXT,
    current_stage     TEXT,
    started_at        TEXT,
    updated_at        TEXT,
    finished_at       TEXT,
    result            TEXT,
    retry_count       INTEGER DEFAULT 0,
    error_message     TEXT,
    UNIQUE(project_key, task_id, started_at)
);
CREATE INDEX IF NOT EXISTS idx_exec_task ON execution_runs(project_key, task_id);

CREATE TABLE IF NOT EXISTS agent_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id   INTEGER NOT NULL,
    agent_name     TEXT NOT NULL,
    pid            INTEGER,
    status         TEXT,
    started_at     TEXT,
    heartbeat_at   TEXT,
    last_output_at TEXT,
    finished_at    TEXT,
    exit_code      INTEGER,
    error_message  TEXT,
    attempt        INTEGER DEFAULT 1,
    cmd            TEXT,
    workdir        TEXT,
    FOREIGN KEY(execution_id) REFERENCES execution_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_agent_exec ON agent_runs(execution_id);

CREATE TABLE IF NOT EXISTS execution_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id INTEGER,
    event_type   TEXT NOT NULL,
    event_time   TEXT NOT NULL,
    details      TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_exec ON execution_events(execution_id);

CREATE TABLE IF NOT EXISTS verification_results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id INTEGER NOT NULL,
    check_name   TEXT NOT NULL,
    status       TEXT NOT NULL,
    evidence     TEXT,
    executed_at  TEXT
);

CREATE TABLE IF NOT EXISTS task_locks (
    project_key TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    pid         INTEGER,
    acquired_at TEXT,
    expires_at  TEXT,
    owner       TEXT,
    PRIMARY KEY(project_key, task_id)
);

CREATE TABLE IF NOT EXISTS pending_writes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_key  TEXT,
    task_id      TEXT,
    action       TEXT NOT NULL,
    payload      TEXT,
    created_at   TEXT,
    attempts     INTEGER DEFAULT 0,
    last_error   TEXT
);
"""


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class StateManager:
    """SQLite 状态管理。线程安全（threading.Lock + WAL）。"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DEFAULT_DB
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.RLock()  # 可重入：持锁方法内可安全调用其他持锁方法
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------- execution_runs
    def create_execution(self, run: ExecutionRun) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO execution_runs
                   (project_key, task_id, task_level, workflow_status, current_stage,
                    started_at, updated_at, retry_count)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    run.project_key,
                    run.task_id,
                    run.task_level.value,
                    run.workflow_status.value,
                    run.current_stage,
                    run.started_at or _now(),
                    _now(),
                    run.retry_count,
                ),
            )
            self._conn.commit()
            eid = int(cur.lastrowid)
        # 记事件放在锁外，避免嵌套持锁（双保险）
        self.log_event(eid, "execution_created", {"task_id": run.task_id})
        return eid

    def update_execution(self, execution_id: int, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "workflow_status", "current_stage", "finished_at", "result",
            "retry_count", "error_message", "task_level",
        }
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k} = ?")
            vals.append(getattr(v, "value", v))
        if not sets:
            return
        sets.append("updated_at = ?")
        vals.append(_now())
        vals.append(execution_id)
        with self._lock:
            self._conn.execute(f"UPDATE execution_runs SET {', '.join(sets)} WHERE id = ?", vals)
            self._conn.commit()

    def get_execution(self, project_key: str, task_id: str) -> Optional[dict]:
        """取该任务**最近一次**执行（用于断点恢复）。"""
        with self._lock:
            row = self._conn.execute(
                """SELECT * FROM execution_runs
                   WHERE project_key=? AND task_id=?
                   ORDER BY id DESC LIMIT 1""",
                (project_key, task_id),
            ).fetchone()
        return dict(row) if row else None

    def list_executions(self, project_key: str | None = None) -> list[dict]:
        with self._lock:
            if project_key:
                rows = self._conn.execute(
                    "SELECT * FROM execution_runs WHERE project_key=? ORDER BY id DESC",
                    (project_key,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM execution_runs ORDER BY id DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------- agent_runs
    def create_agent_run(self, a: AgentRun) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO agent_runs
                   (execution_id, agent_name, pid, status, started_at, attempt, cmd, workdir)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    a.execution_id, a.agent_name, a.pid,
                    a.status.value, a.started_at or _now(),
                    a.attempt, a.cmd, a.workdir,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def update_agent_run(self, agent_run_id: int, **fields: Any) -> None:
        allowed = {
            "pid", "status", "started_at", "heartbeat_at", "last_output_at",
            "finished_at", "exit_code", "error_message",
        }
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k} = ?")
            vals.append(getattr(v, "value", v))
        if not sets:
            return
        vals.append(agent_run_id)
        with self._lock:
            self._conn.execute(f"UPDATE agent_runs SET {', '.join(sets)} WHERE id = ?", vals)
            self._conn.commit()

    def get_agent_runs(self, execution_id: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_runs WHERE execution_id=? ORDER BY id",
                (execution_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def find_live_agent(self, execution_id: int) -> Optional[dict]:
        """找非终态的 agent_run（防重复启动）。"""
        terminal = ("SUCCEEDED", "FAILED", "TIMEOUT", "CANCELLED", "INTERRUPTED")
        ph = ",".join("?" * len(terminal))
        with self._lock:
            row = self._conn.execute(
                f"""SELECT * FROM agent_runs
                    WHERE execution_id=? AND status NOT IN ({ph})
                    ORDER BY id DESC LIMIT 1""",
                (execution_id, *terminal),
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------- events
    def log_event(self, execution_id: int | None, event_type: str, details: dict | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO execution_events (execution_id, event_type, event_time, details) VALUES (?,?,?,?)",
                (execution_id, event_type, _now(), json.dumps(details or {}, ensure_ascii=False)),
            )
            self._conn.commit()

    def get_events(self, execution_id: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM execution_events WHERE execution_id=? ORDER BY id",
                (execution_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["details"] = json.loads(d.get("details") or "{}")
            except Exception:
                pass
            out.append(d)
        return out

    # ------------------------------------------------------- verification
    def save_verification(self, execution_id: int, checks: list[VerifyCheck]) -> None:
        with self._lock:
            for c in checks:
                self._conn.execute(
                    """INSERT INTO verification_results
                       (execution_id, check_name, status, evidence, executed_at)
                       VALUES (?,?,?,?,?)""",
                    (execution_id, c.check_name, c.status.value, c.evidence, c.executed_at),
                )
            self._conn.commit()

    def get_verification(self, execution_id: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM verification_results WHERE execution_id=? ORDER BY id",
                (execution_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------- 任务锁
    def acquire_lock(self, project_key: str, task_id: str, pid: int, owner: str = "agent-manager") -> bool:
        """获取任务锁。已有未过期锁 → False（禁止重复启动）。"""
        now = datetime.datetime.now().astimezone()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM task_locks WHERE project_key=? AND task_id=?",
                (project_key, task_id),
            ).fetchone()
            if row:
                exp = row["expires_at"]
                if exp and exp > now.isoformat(timespec="seconds"):
                    return False  # 未过期 → 有其他实例在跑
                # 已过期 → 检查 PID 是否仍存活
                if row["pid"] and self._pid_alive(row["pid"]):
                    return False
            self._conn.execute(
                """INSERT INTO task_locks (project_key, task_id, pid, acquired_at, expires_at, owner)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(project_key, task_id) DO UPDATE SET
                     pid=excluded.pid, acquired_at=excluded.acquired_at,
                     expires_at=excluded.expires_at, owner=excluded.owner""",
                (
                    project_key, task_id, pid, now.isoformat(timespec="seconds"),
                    (now + datetime.timedelta(seconds=_LOCK_TTL_SECONDS)).isoformat(timespec="seconds"),
                    owner,
                ),
            )
            self._conn.commit()
            return True

    def release_lock(self, project_key: str, task_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM task_locks WHERE project_key=? AND task_id=?",
                (project_key, task_id),
            )
            self._conn.commit()

    def is_locked(self, project_key: str, task_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM task_locks WHERE project_key=? AND task_id=?",
                (project_key, task_id),
            ).fetchone()
        if not row:
            return False
        exp = row["expires_at"]
        return bool(exp and exp > _now())

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if not pid:
            return False
        try:
            import psutil  # type: ignore

            return psutil.pid_exists(pid)
        except ImportError:
            pass
        # Windows / POSIX 兜底
        try:
            if os.name == "nt":
                import ctypes

                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False
            os.kill(pid, 0)
            return True
        except OSError:
            return False
        except Exception:
            return False

    # ------------------------------------------------------- 待回写
    def enqueue_pending_write(self, project_key: str, task_id: str, action: str, payload: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO pending_writes (project_key, task_id, action, payload, created_at, attempts)
                   VALUES (?,?,?,?,?,0)""",
                (project_key, task_id, action, json.dumps(payload, ensure_ascii=False), _now()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get_pending_writes(self, task_id: str | None = None) -> list[dict]:
        with self._lock:
            if task_id:
                rows = self._conn.execute(
                    "SELECT * FROM pending_writes WHERE task_id=? ORDER BY id", (task_id,)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM pending_writes ORDER BY id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload") or "{}")
            except Exception:
                pass
            out.append(d)
        return out

    def mark_write_done(self, write_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM pending_writes WHERE id=?", (write_id,))
            self._conn.commit()

    def mark_write_failed(self, write_id: int, error: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE pending_writes SET attempts=attempts+1, last_error=? WHERE id=?",
                (error[:500], write_id),
            )
            self._conn.commit()
