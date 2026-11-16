# -*- coding: utf-8 -*-
"""HITL — 数据模型与状态机。

决策状态机：
    CREATED -> NOTIFIED -> WAITING_REPLY -> DECISION_RECEIVED -> RESUMING -> RESUMED -> COMPLETED
异常状态：
    NOTIFY_FAILED（重试后仍失败，继续等待回复）
    DECISION_TIMEOUT（超提醒期限仍未回复，**绝不自动批准**；后续仍可回复）
    RESUME_FAILED（恢复原 Session 失败，保留用户决策，可重试）
    REJECTED（用户明确 STOP/驳回）

幂等约束：
    - decision_id 全局唯一
    - 一次决策只允许一次**有效**回复（状态守卫原子转移）
    - 重复回复只记事件，不重复生效
"""
from __future__ import annotations

import datetime
import itertools
import threading
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class DecisionLevel(str, Enum):
    """P0 必须人工批准 / P1 建议人工决策 / P2 Agent 自主处理（不进入流程）"""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class DecisionStatus(str, Enum):
    CREATED = "CREATED"
    NOTIFY_FAILED = "NOTIFY_FAILED"
    NOTIFIED = "NOTIFIED"
    WAITING_REPLY = "WAITING_REPLY"
    DECISION_RECEIVED = "DECISION_RECEIVED"
    RESUMING = "RESUMING"
    RESUMED = "RESUMED"
    COMPLETED = "COMPLETED"
    DECISION_TIMEOUT = "DECISION_TIMEOUT"
    RESUME_FAILED = "RESUME_FAILED"
    REJECTED = "REJECTED"


# 允许状态转移（None 表示不允许；同状态允许重入用于重试记账）
TRANSITIONS: dict[DecisionStatus, set[DecisionStatus]] = {
    DecisionStatus.CREATED: {DecisionStatus.NOTIFIED, DecisionStatus.NOTIFY_FAILED,
                             DecisionStatus.WAITING_REPLY, DecisionStatus.DECISION_RECEIVED,
                             DecisionStatus.REJECTED},
    DecisionStatus.NOTIFY_FAILED: {DecisionStatus.NOTIFIED, DecisionStatus.WAITING_REPLY,
                                   DecisionStatus.DECISION_RECEIVED, DecisionStatus.REJECTED,
                                   DecisionStatus.DECISION_TIMEOUT},
    DecisionStatus.NOTIFIED: {DecisionStatus.WAITING_REPLY, DecisionStatus.DECISION_RECEIVED,
                              DecisionStatus.REJECTED, DecisionStatus.DECISION_TIMEOUT},
    DecisionStatus.WAITING_REPLY: {DecisionStatus.DECISION_RECEIVED, DecisionStatus.REJECTED,
                                   DecisionStatus.DECISION_TIMEOUT},
    DecisionStatus.DECISION_TIMEOUT: {DecisionStatus.DECISION_RECEIVED, DecisionStatus.REJECTED},
    DecisionStatus.DECISION_RECEIVED: {DecisionStatus.RESUMING, DecisionStatus.RESUME_FAILED},
    DecisionStatus.RESUMING: {DecisionStatus.RESUMED, DecisionStatus.RESUME_FAILED},
    DecisionStatus.RESUME_FAILED: {DecisionStatus.RESUMING, DecisionStatus.RESUMED},
    DecisionStatus.RESUMED: {DecisionStatus.COMPLETED},
    DecisionStatus.COMPLETED: set(),
    DecisionStatus.REJECTED: set(),
}

# 仍可接收用户回复的状态（超时后仍允许迟到回复）
REPLYABLE = {
    DecisionStatus.CREATED, DecisionStatus.NOTIFY_FAILED, DecisionStatus.NOTIFIED,
    DecisionStatus.WAITING_REPLY, DecisionStatus.DECISION_TIMEOUT,
}

WAITING_STATES = {DecisionStatus.CREATED, DecisionStatus.NOTIFY_FAILED,
                  DecisionStatus.NOTIFIED, DecisionStatus.WAITING_REPLY,
                  DecisionStatus.DECISION_TIMEOUT}


class ReplyKind(str, Enum):
    OPTION = "option"      # 选择某个方案（A/B/...）
    CUSTOM = "custom"      # 自定义意见（等价方案 C）
    STOP = "stop"          # 暂停任务


class ResumeMethod(str, Enum):
    LIVE_CONTINUE = "live_continue"          # 优先级一：原进程存活，直接续跑
    CC_CONNECT_RESUME = "cc_connect_resume"  # 优先级二：cc-connect 按 agent_session_id 恢复
    CHECKPOINT_REBUILD = "checkpoint_rebuild"  # 优先级三：检查点重建
    NOT_RESUMED = "not_resumed"


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


_seq_lock = threading.Lock()
_seq_counter = itertools.count(1)


def new_decision_id(task_id: str) -> str:
    """DEC-<task_id>-<seq>。seq 为进程内自增 + 时间戳兜底，唯一性最终由存储层保证。"""
    with _seq_lock:
        seq = next(_seq_counter)
    ts = datetime.datetime.now().strftime("%H%M%S")
    return f"DEC-{task_id}-{ts}{seq:02d}"


@dataclass
class DecisionOption:
    id: str
    description: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DecisionRecord:
    """一条人工决策记录（持久化于 human_decisions 表）。"""

    decision_id: str
    task_id: str
    level: DecisionLevel
    question: str
    status: DecisionStatus = DecisionStatus.CREATED
    background: str = ""
    options: list[DecisionOption] = field(default_factory=list)
    recommended_option: Optional[str] = None
    recommend_reason: str = ""
    risk: str = ""
    # 关联
    project_key: str = ""
    agent_id: str = ""
    session_id: str = ""          # Claude Session ID（--resume 用）
    cc_project: str = ""          # cc-connect 项目名
    cc_session_key: str = ""      # cc-connect 会话 key（钉钉会话绑定）
    parent_session_id: Optional[str] = None
    execution_id: Optional[int] = None
    # 回复
    user_reply: Optional[str] = None
    reply_kind: Optional[ReplyKind] = None
    reply_choice: Optional[str] = None
    reply_comment: Optional[str] = None
    reply_user_id: Optional[str] = None
    reply_user_name: Optional[str] = None
    # 时间线
    created_at: str = field(default_factory=_now)
    notified_at: Optional[str] = None
    replied_at: Optional[str] = None
    resumed_at: Optional[str] = None
    completed_at: Optional[str] = None
    deadline_at: Optional[str] = None
    reminded_at: Optional[str] = None
    # 恢复
    resume_method: Optional[ResumeMethod] = None
    last_error: Optional[str] = None

    @property
    def is_waiting(self) -> bool:
        return self.status in WAITING_STATES

    @property
    def is_replyable(self) -> bool:
        return self.status in REPLYABLE

    def to_dict(self) -> dict:
        d = asdict(self)
        d["level"] = self.level.value
        d["status"] = self.status.value
        d["options"] = [o.to_dict() if isinstance(o, DecisionOption) else o for o in self.options]
        if self.reply_kind is not None:
            d["reply_kind"] = self.reply_kind.value
        if self.resume_method is not None:
            d["resume_method"] = self.resume_method.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DecisionRecord":
        opts = [
            o if isinstance(o, DecisionOption) else DecisionOption(id=o["id"], description=o.get("description", ""))
            for o in (d.get("options") or [])
        ]
        return cls(
            decision_id=d["decision_id"],
            task_id=d["task_id"],
            level=DecisionLevel(d["level"]),
            question=d["question"],
            status=DecisionStatus(d.get("status", "CREATED")),
            background=d.get("background", ""),
            options=opts,
            recommended_option=d.get("recommended_option"),
            recommend_reason=d.get("recommend_reason", ""),
            risk=d.get("risk", ""),
            project_key=d.get("project_key", ""),
            agent_id=d.get("agent_id", ""),
            session_id=d.get("session_id", ""),
            cc_project=d.get("cc_project", ""),
            cc_session_key=d.get("cc_session_key", ""),
            parent_session_id=d.get("parent_session_id"),
            execution_id=d.get("execution_id"),
            user_reply=d.get("user_reply"),
            reply_kind=ReplyKind(d["reply_kind"]) if d.get("reply_kind") else None,
            reply_choice=d.get("reply_choice"),
            reply_comment=d.get("reply_comment"),
            reply_user_id=d.get("reply_user_id"),
            reply_user_name=d.get("reply_user_name"),
            created_at=d.get("created_at") or _now(),
            notified_at=d.get("notified_at"),
            replied_at=d.get("replied_at"),
            resumed_at=d.get("resumed_at"),
            completed_at=d.get("completed_at"),
            deadline_at=d.get("deadline_at"),
            reminded_at=d.get("reminded_at"),
            resume_method=ResumeMethod(d["resume_method"]) if d.get("resume_method") else None,
            last_error=d.get("last_error"),
        )


@dataclass
class ParsedReply:
    """reply_parser 输出。"""

    decision_id: Optional[str]  # 显式携带的 DEC-ID（可空）
    kind: ReplyKind
    choice: Optional[str] = None      # 方案 id（OPTION/CUSTOM 时）
    comment: Optional[str] = None     # 附带意见
    raw_text: str = ""
    valid: bool = True
    invalid_reason: str = ""


@dataclass
class ReplyRecord:
    """一次用户回复（含被拒绝的），全部留痕。"""

    decision_id: str
    raw_text: str
    source: str                      # hook | watch | cli | mgmt | test
    accepted: bool = False
    reject_reason: str = ""
    reply_user_id: Optional[str] = None
    reply_user_name: Optional[str] = None
    msg_id: Optional[str] = None
    parsed_choice: Optional[str] = None
    parsed_comment: Optional[str] = None
    kind: Optional[ReplyKind] = None
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.kind is not None:
            d["kind"] = self.kind.value
        return d
