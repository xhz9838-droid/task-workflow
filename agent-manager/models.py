# -*- coding: utf-8 -*-
"""P11 Agent Execution Manager — 统一数据模型与状态机。

状态机（Agent 级）：
    PENDING -> STARTING -> RUNNING -> SUCCEEDED | FAILED | TIMEOUT | CANCELLED | INTERRUPTED

任务级额外状态：
    RETRY_WAIT, VERIFYING, BLOCKED, COMPLETED

关键区分（不得混淆）：
    Agent 进程退出码 0  !=  开发任务完成。任务完成由 Verifier 判定。
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


# --------------------------------------------------------------- 枚举
class TaskLevel(str, Enum):
    """任务等级（P11 Task Router）"""

    S = "S"  # 简单：Main Agent 直通，不启动子 Agent
    M = "M"  # 中等：按需选择性启动子 Agent
    L = "L"  # 大型：完整多 Agent 工作流


class WorkflowType(str, Enum):
    DIRECT = "direct"  # S：Main Agent 直接完成
    SELECTIVE = "selective"  # M：按需子 Agent
    FULL = "full"  # L：完整流程


class AgentState(str, Enum):
    PENDING = "PENDING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


class TaskState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    VERIFYING = "VERIFYING"
    BLOCKED = "BLOCKED"
    # HITL 阻塞：Agent 已发起人工决策，等待用户回复（T06）
    # 与 BLOCKED 区分：BLOCKED 是环境/依赖阻塞，WAITING_HUMAN 是主动等待人工
    WAITING_HUMAN = "WAITING_HUMAN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VerifyStatus(str, Enum):
    """验证结果五态 —— 绝不互相混淆"""

    PASS = "PASS"  # 实际执行且通过
    FAIL = "FAIL"  # 实际执行但失败
    BLOCKED = "BLOCKED"  # 环境/权限原因无法执行
    SKIPPED = "SKIPPED"  # 按策略或用户要求跳过
    NOT_RUN = "NOT_RUN"  # 尚未执行

    def is_passable(self) -> bool:
        """只有 PASS 才算通过。BLOCKED/SKIPPED/NOT_RUN 绝不视为通过。

        可用作实例方法（`st.is_passable()`）或静态判定（`VerifyStatus.is_passable(st)`）。
        """
        return VerifyStatus(self) == VerifyStatus.PASS


class FaultClass(str, Enum):
    """故障分类 —— 决定是否允许自动重试"""

    TRANSIENT = "TRANSIENT"  # 可自动重试：网络抖动/超时/瞬时资源
    PERMANENT = "PERMANENT"  # 不可自动重试：代码错误/测试失败/需求不明/权限不足
    HUMAN = "HUMAN"  # 需人工：业务决策/用户取消/状态冲突


# 终态集合
AGENT_TERMINAL = {
    AgentState.SUCCEEDED,
    AgentState.FAILED,
    AgentState.TIMEOUT,
    AgentState.CANCELLED,
    AgentState.INTERRUPTED,
}
TASK_TERMINAL = {
    TaskState.COMPLETED,
    TaskState.FAILED,
    TaskState.CANCELLED,
}


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------- 数据类
@dataclass
class RouteDecision:
    """Task Router 输出 —— 每个任务启动时必须记录"""

    task_id: str
    project_key: str
    task_level: TaskLevel
    classification_reason: str
    selected_workflow: WorkflowType
    selected_agents: list[str] = field(default_factory=list)
    expected_tests: list[str] = field(default_factory=list)
    execution_budget_seconds: int = 1800
    user_overrides: dict[str, Any] = field(default_factory=dict)
    decided_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["task_level"] = self.task_level.value
        d["selected_workflow"] = self.selected_workflow.value
        return d


@dataclass
class AgentSpec:
    """单个子 Agent 的派发规格（文件所有权 + 完成条件）"""

    name: str
    purpose: str
    files_owned: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    timeout_seconds: int = 1800

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AgentRun:
    """一次子 Agent 进程运行记录"""

    execution_id: int
    agent_name: str
    pid: Optional[int] = None
    status: AgentState = AgentState.PENDING
    started_at: Optional[str] = None
    heartbeat_at: Optional[str] = None  # 无可靠心跳源时为 None
    last_output_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    error_message: Optional[str] = None
    attempt: int = 1
    cmd: str = ""
    workdir: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in AGENT_TERMINAL

    def touch_output(self) -> None:
        self.last_output_at = _now()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerifyCheck:
    """单个验证项"""

    check_name: str
    status: VerifyStatus
    evidence: str = ""
    executed_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class VerifyReport:
    """Verifier 输出（P11 §五）"""

    git_status: VerifyStatus = VerifyStatus.NOT_RUN
    changed_files: list[str] = field(default_factory=list)
    commit: str = ""
    tests: dict[str, VerifyStatus] = field(default_factory=dict)
    requirements_status: VerifyStatus = VerifyStatus.NOT_RUN
    requirements_details: list[str] = field(default_factory=list)
    checks: list[VerifyCheck] = field(default_factory=list)
    blocked_summary: Optional[str] = None  # BLOCKED 聚合说明
    overall: str = "NOT_RUN"

    def compute_overall(self) -> str:
        """按真实证据计算 overall。绝不把 BLOCKED/SKIPPED/NOT_RUN 算成 SUCCESS。"""
        statuses = [self.git_status, self.requirements_status, *self.tests.values()]
        if any(s == VerifyStatus.FAIL for s in statuses):
            self.overall = "FAILED"
        elif any(s == VerifyStatus.PASS for s in statuses):
            # 有 PASS 但也有非 PASS → 部分完成
            if all(s == VerifyStatus.PASS for s in statuses):
                self.overall = "SUCCESS"
            else:
                self.overall = "PARTIAL"
        else:
            self.overall = "NOT_RUN"
        return self.overall

    def to_dict(self) -> dict:
        return {
            "git": {
                "status": self.git_status.value,
                "changed_files": self.changed_files,
                "commit": self.commit,
            },
            "tests": {k: v.value for k, v in self.tests.items()},
            "requirements": {
                "status": self.requirements_status.value,
                "details": self.requirements_details,
            },
            "blocked_summary": self.blocked_summary,
            "checks": [c.to_dict() for c in self.checks],
            "overall": self.compute_overall(),
        }


@dataclass
class ExecutionRun:
    """一次任务级执行"""

    project_key: str
    task_id: str
    task_level: TaskLevel = TaskLevel.M
    workflow_status: TaskState = TaskState.PENDING
    current_stage: str = ""
    started_at: Optional[str] = None
    updated_at: str = field(default_factory=_now)
    finished_at: Optional[str] = None
    result: Optional[str] = None
    retry_count: int = 0
    error_message: Optional[str] = None
    execution_id: Optional[int] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["task_level"] = self.task_level.value
        d["workflow_status"] = self.workflow_status.value
        return d
