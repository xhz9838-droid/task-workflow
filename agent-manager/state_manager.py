# -*- coding: utf-8 -*-
"""P11 Phase 2 — State Manager：SQLite 状态持久化 + 任务锁 + 断点恢复。

表结构（P11 §六）：
    execution_runs      任务级执行
    agent_runs          子 Agent 运行（Claude CLI subprocess 级）
    node_dispatches     DAG 节点级派发凭证（Agent Tool agent_id / CLI pid 统一记录）
    execution_events    事件流（审计/恢复）
    verification_results 验证结果
    task_locks          任务级锁（防重复启动）
    pending_writes      待回写禅道事件（失败不丢）

设计要点：
    - 状态不只在内存，管理器异常退出后可恢复
    - 同一 task_id 只能有一个有效运行实例（任务锁 + 过期检查）
    - 恢复时核对 PID + 启动时间 + 工作目录，避免 PID 重用误判
    - 防并发写（SQLite 事务 + WAL）
    - **DAG 节点状态唯一真相源**：node_dispatches 记录每个 (node_id, attempt) 的
      状态机与执行凭证；run-state.json 由 dispatch.py export-state 从此导出。
    - **执行后端区分**：execution_backend ∈ {claude_tool, cli_subprocess}。
      claude_tool 只有 agent_id（无 pid、无存活探测能力），cli_subprocess 有 pid。
      reconcile 对 claude_tool 的 RUNNING 无法 pid 探活 → UNVERIFIED，不伪造。
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
    from .models import (
        AgentRun, AgentState, ExecutionRun, NodeDispatch, NodeState,
        ExecutionBackend, TaskState, VerifyCheck, VerifyStatus,
        _NODE_TRANSITIONS, NODE_NON_TERMINAL,
    )
    from .exceptions import DuplicateExecutionError
except ImportError:
    from models import (  # type: ignore
        AgentRun, AgentState, ExecutionRun, NodeDispatch, NodeState,
        ExecutionBackend, TaskState, VerifyCheck, VerifyStatus,
        _NODE_TRANSITIONS, NODE_NON_TERMINAL,
    )
    from exceptions import DuplicateExecutionError  # type: ignore

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
    error_message     TEXT
);
-- 注：不加 UNIQUE(project_key, task_id, started_at)——started_at 秒级精度会同秒撞键，
--     并发防护由 task_locks 负责，历史允许多条执行记录。
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

-- DAG 节点级派发凭证：DAG 节点状态机的唯一真相源（run-state.json 由 export-state 从此导出）
-- 同一 (node_id, attempt_id) 唯一；不同 attempt 隔离，旧 attempt 迟到通知不覆盖新 attempt。
CREATE TABLE IF NOT EXISTS node_dispatches (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id        INTEGER NOT NULL,
    node_id             TEXT NOT NULL,
    attempt_id          TEXT NOT NULL,
    agent_name          TEXT NOT NULL,
    execution_backend   TEXT NOT NULL,   -- claude_tool | cli_subprocess
    status              TEXT NOT NULL,   -- NodeState
    agent_id            TEXT,            -- CLAUDE_TOOL 返回的 id；CLI 为 NULL
    pid                 INTEGER,         -- CLI_SUBPROCESS pid；CLAUDE_TOOL 为 NULL
    started_at          TEXT,
    dispatch_started_at TEXT,
    finished_at         TEXT,
    last_seen_at        TEXT,
    error_code          TEXT,
    error_message       TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY(execution_id) REFERENCES execution_runs(id)
);
-- 唯一约束：(execution_id, node_id, attempt_id) 全局唯一，防重复登记同一 attempt
CREATE UNIQUE INDEX IF NOT EXISTS ux_node_dispatch ON node_dispatches(execution_id, node_id, attempt_id);
-- 节点最新 attempt 查询：按 (execution_id, node_id) 取 id 最大（最近登记）的一行
CREATE INDEX IF NOT EXISTS idx_node_dispatch_node ON node_dispatches(execution_id, node_id, id);
-- 对账：未终结 + DISPATCHING/RUNNING 的节点
CREATE INDEX IF NOT EXISTS idx_node_dispatch_status ON node_dispatches(execution_id, status);
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
            try:
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
            except Exception as e:
                # 旧库遗留 UNIQUE 约束时同秒撞键：重试一次（时间戳微秒化）
                if "UNIQUE" in str(e):
                    cur = self._conn.execute(
                        """INSERT INTO execution_runs
                           (project_key, task_id, task_level, workflow_status, current_stage,
                            started_at, updated_at, retry_count)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (
                            run.project_key, run.task_id, run.task_level.value,
                            run.workflow_status.value, run.current_stage,
                            _now() + "Z", _now(), run.retry_count,
                        ),
                    )
                    self._conn.commit()
                    eid = int(cur.lastrowid)
                else:
                    raise
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

    # ------------------------------------------------------- node_dispatches
    def register_node_dispatch(self, nd: NodeDispatch) -> int:
        """登记一次 DAG 节点派发（DISPATCHING + attempt_id）。

        事务原子写入：插入一行 node_dispatches，status=DISPATCHING，
        dispatch_started_at=now。同 (execution_id, node_id, attempt_id) 已存在
        → 抛 DuplicateExecutionError（防同一 attempt 重复登记）。

        不在此取得 agent_id/pid——那是主控调 Agent Tool 之后 confirm-running 的事。
        DISPATCHING 是"已登记准备派发"，不是"已运行"。
        """
        now = _now()
        with self._lock:
            try:
                cur = self._conn.execute(
                    """INSERT INTO node_dispatches
                       (execution_id, node_id, attempt_id, agent_name, execution_backend,
                        status, dispatch_started_at, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        nd.execution_id, nd.node_id, nd.attempt_id, nd.agent_name,
                        nd.execution_backend.value,
                        NodeState.DISPATCHING.value, now, now, now,
                    ),
                )
                self._conn.commit()
                nid = int(cur.lastrowid)
            except sqlite3.IntegrityError as e:
                raise DuplicateExecutionError(
                    "节点 %s attempt %s 已登记，禁止重复派发（用新 attempt_id 重试）"
                    % (nd.node_id, nd.attempt_id)
                ) from e
        self.log_event(nd.execution_id, "node_dispatch_registered", {
            "node_id": nd.node_id, "attempt_id": nd.attempt_id,
            "agent_name": nd.agent_name, "backend": nd.execution_backend.value,
        })
        return nid

    def get_node_dispatch(self, execution_id: int, node_id: str, attempt_id: str) -> Optional[dict]:
        """精确取某 attempt 凭证。"""
        with self._lock:
            row = self._conn.execute(
                """SELECT * FROM node_dispatches
                   WHERE execution_id=? AND node_id=? AND attempt_id=?""",
                (execution_id, node_id, attempt_id),
            ).fetchone()
        return dict(row) if row else None

    def latest_node_dispatch(self, execution_id: int, node_id: str) -> Optional[dict]:
        """取节点最新 attempt（id 最大=最近登记）。用于查节点当前态。"""
        with self._lock:
            row = self._conn.execute(
                """SELECT * FROM node_dispatches
                   WHERE execution_id=? AND node_id=?
                   ORDER BY id DESC LIMIT 1""",
                (execution_id, node_id),
            ).fetchone()
        return dict(row) if row else None

    def list_node_dispatches(self, execution_id: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM node_dispatches WHERE execution_id=?
                   ORDER BY node_id, id""",
                (execution_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def assert_node_transition(from_state: NodeState, to_state: NodeState) -> None:
        """校验 NodeState 转换合法性。非法转换抛 ValueError（不静默写错态）。"""
        allowed = _NODE_TRANSITIONS.get(from_state, frozenset())
        if to_state not in allowed:
            raise ValueError(
                "非法节点状态转换: %s → %s（允许: %s）"
                % (from_state.value, to_state.value, ", ".join(sorted(s.value for s in allowed)))
            )

    def update_node_dispatch(
        self, execution_id: int, node_id: str, attempt_id: str, **fields: Any
    ) -> dict:
        """更新某 attempt 凭证字段并校验状态转换。

        事务：读旧 status → assert_node_transition → 写新字段 + updated_at。
        旧 attempt（非最新）的迟到通知：写入记事件但不改"最新 attempt"语义——
        调用方应传具体 attempt_id，reconcile 据此判定是否迟到。
        """
        allowed = {
            "status", "agent_id", "pid", "started_at", "finished_at",
            "last_seen_at", "error_code", "error_message",
        }
        sets, vals = [], []
        new_status = None
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "status":
                new_status = v
                v = getattr(v, "value", v)
            sets.append(f"{k} = ?")
            vals.append(v)
        if not sets:
            raise ValueError("无有效字段更新 node_dispatch")
        sets.append("updated_at = ?")
        vals.append(_now())
        vals.extend([execution_id, node_id, attempt_id])
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM node_dispatches WHERE execution_id=? AND node_id=? AND attempt_id=?",
                (execution_id, node_id, attempt_id),
            ).fetchone()
            if not row:
                raise KeyError(
                    "node_dispatch 不存在: exec=%s node=%s attempt=%s" % (execution_id, node_id, attempt_id)
                )
            old_status = NodeState(row["status"])
            if new_status is not None:
                self.assert_node_transition(old_status, new_status)
            self._conn.execute(
                f"""UPDATE node_dispatches SET {', '.join(sets)}
                    WHERE execution_id=? AND node_id=? AND attempt_id=?""",
                vals,
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM node_dispatches WHERE execution_id=? AND node_id=? AND attempt_id=?",
                (execution_id, node_id, attempt_id),
            ).fetchone()
            updated = dict(row)
        self.log_event(execution_id, "node_dispatch_updated", {
            "node_id": node_id, "attempt_id": attempt_id,
            "from": old_status.value, "to": (new_status.value if new_status else old_status.value),
        })
        return updated

    def confirm_node_running(
        self, execution_id: int, node_id: str, attempt_id: str,
        *, agent_id: Optional[str] = None, pid: Optional[int] = None,
    ) -> dict:
        """主控取得真实 agent_id（Agent Tool）/ pid（CLI）后确认 RUNNING。

        DISPATCHING → RUNNING。agent_id/pid 二选一按 backend：
          CLAUDE_TOOL    → agent_id 必填，pid=None
          CLI_SUBPROCESS → pid 必填，agent_id=None
        不得伪造：backend=claude_tool 时不接受 pid。
        """
        with self._lock:
            row = self._conn.execute(
                """SELECT execution_backend FROM node_dispatches
                   WHERE execution_id=? AND node_id=? AND attempt_id=?""",
                (execution_id, node_id, attempt_id),
            ).fetchone()
            if not row:
                raise KeyError("node_dispatch 不存在: %s/%s/%s" % (execution_id, node_id, attempt_id))
            backend = ExecutionBackend(row["execution_backend"])
        if backend == ExecutionBackend.CLAUDE_TOOL:
            if not agent_id:
                raise ValueError("CLAUDE_TOOL backend 必须提供 agent_id（不伪造 pid）")
            pid = None  # Agent Tool 无 pid，强制 None
        else:
            if not pid:
                raise ValueError("CLI_SUBPROCESS backend 必须提供 pid")
            agent_id = None
        now = _now()
        return self.update_node_dispatch(
            execution_id, node_id, attempt_id,
            status=NodeState.RUNNING, agent_id=agent_id, pid=pid,
            started_at=now, last_seen_at=now,
        )

    def record_node_result(
        self, execution_id: int, node_id: str, attempt_id: str,
        *, status: NodeState, error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> dict:
        """记录节点终态/失败：RUNNING→DONE/FAILED/BLOCKED，或 DISPATCHING→FAILED。

        Agent 报告存在 ≠ 节点自动 DONE——DONE 仍需主控验收规则（continuation-protocol 规则4）。
        本方法只记录执行层结果；验收层由 verifier + 主控决定是否推进 DAG。
        """
        now = _now()
        return self.update_node_dispatch(
            execution_id, node_id, attempt_id,
            status=status, finished_at=now,
            error_code=error_code, error_message=(error_message[:500] if error_message else None),
        )

    def is_latest_attempt(self, execution_id: int, node_id: str, attempt_id: str) -> bool:
        """该 attempt 是否为节点最新 attempt。用于迟到通知判定。"""
        latest = self.latest_node_dispatch(execution_id, node_id)
        return bool(latest and latest["attempt_id"] == attempt_id)

    def list_open_node_dispatches(self, execution_id: int) -> list[dict]:
        """所有未到 DONE 的节点最新 attempt（reconcile 用）。"""
        with self._lock:
            rows = self._conn.execute(
                """SELECT nd.* FROM node_dispatches nd
                   INNER JOIN (
                       SELECT node_id, MAX(id) AS max_id
                       FROM node_dispatches WHERE execution_id=?
                       GROUP BY node_id
                   ) m ON nd.node_id = m.node_id AND nd.id = m.max_id
                   WHERE nd.execution_id=? AND nd.status != ?""",
                (execution_id, execution_id, NodeState.DONE.value),
            ).fetchall()
        return [dict(r) for r in rows]
