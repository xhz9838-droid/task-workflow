# -*- coding: utf-8 -*-
"""HITL — 决策持久化（复用 agent-manager SQLite：logs/agent_manager.db）。

与 P11 StateManager 共用同一 SQLite 文件与 WAL/锁风格，表为新增（不改旧表）：
    human_decisions   决策主表
    decision_replies  回复流水（含被拒绝的，全部留痕）
    decision_events   决策事件流（审计/恢复）

幂等保证：
    - decision_id PRIMARY KEY
    - 状态转移用条件 UPDATE（WHERE status IN ...）原子守卫，一次决策只生效一次回复
    - 回复按 (decision_id, msg_id) 唯一去重
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import threading
from typing import Any, Optional

import sys  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)  # agent-manager/
for _p in (_PARENT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human_decision.models import (  # noqa: E402
    DecisionRecord,
    DecisionStatus,
    ReplyRecord,
    ReplyKind,
    ResumeMethod,
    _now,
)

DEFAULT_DB = os.path.join(_PARENT, "logs", "agent_manager.db")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS human_decisions (
    decision_id        TEXT PRIMARY KEY,
    project_key        TEXT,
    task_id            TEXT NOT NULL,
    agent_id           TEXT,
    session_id         TEXT,
    cc_project         TEXT,
    cc_session_key     TEXT,
    parent_session_id  TEXT,
    execution_id       INTEGER,
    decision_level     TEXT NOT NULL,
    status             TEXT NOT NULL,
    question           TEXT NOT NULL,
    background         TEXT,
    options            TEXT,
    recommended_option TEXT,
    recommend_reason   TEXT,
    risk               TEXT,
    user_reply         TEXT,
    reply_kind         TEXT,
    reply_choice       TEXT,
    reply_comment      TEXT,
    reply_user_id      TEXT,
    reply_user_name    TEXT,
    created_at         TEXT NOT NULL,
    notified_at        TEXT,
    replied_at         TEXT,
    resumed_at         TEXT,
    completed_at       TEXT,
    deadline_at        TEXT,
    reminded_at        TEXT,
    resume_method      TEXT,
    last_error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_hd_task ON human_decisions(project_key, task_id);
CREATE INDEX IF NOT EXISTS idx_hd_status ON human_decisions(status);

CREATE TABLE IF NOT EXISTS decision_replies (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id    TEXT NOT NULL,
    raw_text       TEXT,
    parsed_choice  TEXT,
    parsed_comment TEXT,
    kind           TEXT,
    reply_user_id  TEXT,
    reply_user_name TEXT,
    source         TEXT,
    msg_id         TEXT,
    accepted       INTEGER DEFAULT 0,
    reject_reason  TEXT,
    created_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_dr_decision ON decision_replies(decision_id);

CREATE TABLE IF NOT EXISTS decision_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT,
    event       TEXT NOT NULL,
    event_time  TEXT NOT NULL,
    details     TEXT
);
CREATE INDEX IF NOT EXISTS idx_de_decision ON decision_events(decision_id);
"""


class DecisionStore:
    """SQLite 决策存储。线程安全（threading.Lock + WAL）。"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DEFAULT_DB
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------- 写入
    def create(self, rec: DecisionRecord) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO human_decisions (
                    decision_id, project_key, task_id, agent_id, session_id,
                    cc_project, cc_session_key, parent_session_id, execution_id,
                    decision_level, status, question, background, options,
                    recommended_option, recommend_reason, risk,
                    created_at, deadline_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rec.decision_id, rec.project_key, rec.task_id, rec.agent_id, rec.session_id,
                    rec.cc_project, rec.cc_session_key, rec.parent_session_id, rec.execution_id,
                    rec.level.value, rec.status.value, rec.question, rec.background,
                    json.dumps([o.to_dict() for o in rec.options], ensure_ascii=False),
                    rec.recommended_option, rec.recommend_reason, rec.risk,
                    rec.created_at, rec.deadline_at,
                ),
            )
            self._conn.commit()
        self.log_event(rec.decision_id, "created", {"level": rec.level.value, "task_id": rec.task_id})

    def get(self, decision_id: str) -> Optional[DecisionRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM human_decisions WHERE decision_id=?", (decision_id,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list(
        self,
        *,
        status: str | DecisionStatus | None = None,
        task_id: str | None = None,
        project_key: str | None = None,
        limit: int = 50,
    ) -> list[DecisionRecord]:
        q = "SELECT * FROM human_decisions WHERE 1=1"
        args: list[Any] = []
        if status is not None:
            q += " AND status=?"
            args.append(getattr(status, "value", status))
        if task_id is not None:
            q += " AND task_id=?"
            args.append(task_id)
        if project_key is not None:
            q += " AND project_key=?"
            args.append(project_key)
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        return [self._row_to_record(r) for r in rows]

    def list_waiting(self) -> list[DecisionRecord]:
        """所有等待中的决策（恢复/超时扫描用）。"""
        from human_decision.models import WAITING_STATES

        ph = ",".join("?" * len(WAITING_STATES))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM human_decisions WHERE status IN ({ph}) ORDER BY created_at",
                tuple(s.value for s in WAITING_STATES),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    # ------------------------------------------------------- 状态转移（原子守卫）
    def transition(
        self,
        decision_id: str,
        to_status: DecisionStatus,
        *,
        allowed_from: set[DecisionStatus] | None = None,
        fields: dict | None = None,
    ) -> bool:
        """条件转移。返回 False 表示守卫未通过（重复处理/非法转移）。

        fields 内允许的列：user_reply, reply_kind, reply_choice, reply_comment,
        reply_user_id, reply_user_name, notified_at, replied_at, resumed_at,
        completed_at, reminded_at, resume_method, last_error, deadline_at。
        """
        sets = ["status=?"]
        vals: list[Any] = [to_status.value]
        allowed_cols = {
            "user_reply", "reply_kind", "reply_choice", "reply_comment",
            "reply_user_id", "reply_user_name", "notified_at", "replied_at",
            "resumed_at", "completed_at", "reminded_at", "resume_method",
            "last_error", "deadline_at",
        }
        for k, v in (fields or {}).items():
            if k not in allowed_cols:
                continue
            sets.append(f"{k}=?")
            vals.append(getattr(v, "value", v))
        # WHERE 占位符顺序：decision_id 在前，allowed_from 在后
        vals.append(decision_id)
        if allowed_from:
            ph = ",".join("?" * len(allowed_from))
            cond = f" AND status IN ({ph})"
            vals.extend(s.value for s in allowed_from)
        else:
            cond = ""
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE human_decisions SET {', '.join(sets)} WHERE decision_id=?{cond}",
                vals,
            )
            self._conn.commit()
        ok = cur.rowcount == 1
        if ok:
            self.log_event(decision_id, "status", {"to": to_status.value, "fields": list((fields or {}).keys())})
        return ok

    def update_fields(self, decision_id: str, **fields: Any) -> None:
        """无状态守卫的字段更新（如 deadline/last_error）。"""
        allowed = {
            "session_id", "cc_project", "cc_session_key", "deadline_at",
            "reminded_at", "last_error", "resume_method", "execution_id",
            "notified_at", "agent_id",
        }
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k}=?")
            vals.append(getattr(v, "value", v))
        if not sets:
            return
        vals.append(decision_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE human_decisions SET {', '.join(sets)} WHERE decision_id=?", vals
            )
            self._conn.commit()

    # ------------------------------------------------------- 回复流水
    def record_reply(self, rep: ReplyRecord) -> Optional[int]:
        """记录回复。msg_id 相同的重复投递不重复插入。返回记录 id；重复返回 None。"""
        with self._lock:
            if rep.msg_id:
                dup = self._conn.execute(
                    "SELECT id FROM decision_replies WHERE decision_id=? AND msg_id=?",
                    (rep.decision_id, rep.msg_id),
                ).fetchone()
                if dup:
                    return None
            cur = self._conn.execute(
                """INSERT INTO decision_replies
                   (decision_id, raw_text, parsed_choice, parsed_comment, kind,
                    reply_user_id, reply_user_name, source, msg_id, accepted,
                    reject_reason, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rep.decision_id, rep.raw_text, rep.parsed_choice, rep.parsed_comment,
                    rep.kind.value if rep.kind else None, rep.reply_user_id, rep.reply_user_name,
                    rep.source, rep.msg_id, 1 if rep.accepted else 0, rep.reject_reason,
                    rep.created_at,
                ),
            )
            self._conn.commit()
            rid = int(cur.lastrowid)
        self.log_event(
            rep.decision_id,
            "reply_accepted" if rep.accepted else "reply_rejected",
            {"source": rep.source, "reason": rep.reject_reason, "choice": rep.parsed_choice},
        )
        return rid

    def replies(self, decision_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM decision_replies WHERE decision_id=? ORDER BY id", (decision_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------- 事件
    def log_event(self, decision_id: str | None, event: str, details: dict | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO decision_events (decision_id, event, event_time, details) VALUES (?,?,?,?)",
                (decision_id, event, _now(), json.dumps(details or {}, ensure_ascii=False)),
            )
            self._conn.commit()

    def events(self, decision_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM decision_events WHERE decision_id=? ORDER BY id", (decision_id,)
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

    # ------------------------------------------------------- 内部
    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> DecisionRecord:
        d = dict(row)
        try:
            opts = json.loads(d.get("options") or "[]")
        except Exception:
            opts = []
        flat = {
            "decision_id": d["decision_id"],
            "task_id": d["task_id"],
            "level": d["decision_level"],
            "question": d["question"],
            "status": d["status"],
            "background": d.get("background") or "",
            "options": opts,
            "recommended_option": d.get("recommended_option"),
            "recommend_reason": d.get("recommend_reason") or "",
            "risk": d.get("risk") or "",
            "project_key": d.get("project_key") or "",
            "agent_id": d.get("agent_id") or "",
            "session_id": d.get("session_id") or "",
            "cc_project": d.get("cc_project") or "",
            "cc_session_key": d.get("cc_session_key") or "",
            "parent_session_id": d.get("parent_session_id"),
            "execution_id": d.get("execution_id"),
            "user_reply": d.get("user_reply"),
            "reply_kind": d.get("reply_kind"),
            "reply_choice": d.get("reply_choice"),
            "reply_comment": d.get("reply_comment"),
            "reply_user_id": d.get("reply_user_id"),
            "reply_user_name": d.get("reply_user_name"),
            "created_at": d.get("created_at"),
            "notified_at": d.get("notified_at"),
            "replied_at": d.get("replied_at"),
            "resumed_at": d.get("resumed_at"),
            "completed_at": d.get("completed_at"),
            "deadline_at": d.get("deadline_at"),
            "reminded_at": d.get("reminded_at"),
            "resume_method": d.get("resume_method"),
            "last_error": d.get("last_error"),
        }
        return DecisionRecord.from_dict(flat)
