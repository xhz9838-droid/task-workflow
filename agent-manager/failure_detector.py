# -*- coding: utf-8 -*-
"""P11 T07 — 失败检测与异常分类。

识别 Agent 执行结果（P11 §T07）：
    正常完成 / 非零退出 / 执行超时 / 进程异常消失
    MCP 调用失败 / 通知失败 / HITL 等待超时

异常分类具备扩展性，避免所有异常归为普通执行失败。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from enum import Enum

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from .models import FaultClass
except ImportError:
    from models import FaultClass  # type: ignore


class FailureKind(str, Enum):
    """失败类型（T07 表格）"""

    NONE = "none"                # 正常完成
    NONZERO_EXIT = "nonzero_exit"        # Agent 非零退出
    TIMEOUT = "timeout"                  # 执行超时
    PROCESS_LOST = "process_lost"        # 进程异常消失
    MCP_FAILURE = "mcp_failure"          # MCP 调用失败
    NOTIFY_FAILURE = "notify_failure"    # 网络/通知失败
    HITL_TIMEOUT = "hitl_timeout"        # HITL 等待超时（不自动批准）
    UNKNOWN = "unknown"


# 失败类型 → 故障分类（决定重试策略）
KIND_TO_FAULT: dict[FailureKind, FaultClass] = {
    FailureKind.NONE: FaultClass.PERMANENT,
    FailureKind.NONZERO_EXIT: FaultClass.PERMANENT,   # 代码错误，不盲目重试
    FailureKind.TIMEOUT: FaultClass.PERMANENT,        # 阶段超时，需分析
    FailureKind.PROCESS_LOST: FaultClass.PERMANENT,   # 进程消失，需分析
    FailureKind.MCP_FAILURE: FaultClass.TRANSIENT,    # 瞬时，可重试
    FailureKind.NOTIFY_FAILURE: FaultClass.TRANSIENT, # 瞬时，可重试
    FailureKind.HITL_TIMEOUT: FaultClass.HUMAN,       # 人工，不重试不批准
    FailureKind.UNKNOWN: FaultClass.PERMANENT,
}


@dataclass
class FailureReport:
    kind: FailureKind
    fault: FaultClass
    detail: str = ""
    exit_code: int | None = None
    retryable: bool = False
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "fault": self.fault.value,
            "detail": self.detail,
            "exit_code": self.exit_code,
            "retryable": self.retryable,
            "extra": self.extra,
        }


class FailureDetector:
    """识别 Agent 执行失败类型。"""

    @staticmethod
    def from_exit(exit_code: int | None, *, timed_out: bool = False,
                  process_lost: bool = False) -> FailureReport:
        """从进程退出信息判定失败类型。"""
        if process_lost:
            return FailureReport(
                kind=FailureKind.PROCESS_LOST,
                fault=KIND_TO_FAULT[FailureKind.PROCESS_LOST],
                detail="Agent 进程异常消失",
                exit_code=exit_code,
            )
        if timed_out:
            return FailureReport(
                kind=FailureKind.TIMEOUT,
                fault=KIND_TO_FAULT[FailureKind.TIMEOUT],
                detail=f"Agent 执行超时（exit={exit_code}）",
                exit_code=exit_code,
            )
        if exit_code is None:
            return FailureReport(
                kind=FailureKind.UNKNOWN,
                fault=FaultClass.PERMANENT,
                detail="退出码未知",
            )
        if exit_code == 0:
            return FailureReport(
                kind=FailureKind.NONE,
                fault=FaultClass.PERMANENT,
                detail="正常完成",
                exit_code=0,
            )
        return FailureReport(
            kind=FailureKind.NONZERO_EXIT,
            fault=KIND_TO_FAULT[FailureKind.NONZERO_EXIT],
            detail=f"Agent 非零退出（exit={exit_code}）",
            exit_code=exit_code,
        )

    @staticmethod
    def from_error(error: BaseException | str) -> FailureReport:
        """从异常/消息判定失败类型。"""
        try:
            from .retry import classify_fault
        except ImportError:
            from retry import classify_fault  # type: ignore
        text = str(error).lower()
        fault = classify_fault(error)

        if "hitl" in text or "human decision" in text or "waiting for human" in text:
            kind = FailureKind.HITL_TIMEOUT
        elif "mcp" in text or "tool call" in text or "jsonrpc" in text:
            kind = FailureKind.MCP_FAILURE
        elif "notify" in text or "dingtalk" in text or "notification" in text:
            kind = FailureKind.NOTIFY_FAILURE
        elif "timeout" in text or "timed out" in text:
            kind = FailureKind.TIMEOUT
        elif "process" in text and ("disappear" in text or "not found" in text):
            kind = FailureKind.PROCESS_LOST
        else:
            kind = FailureKind.UNKNOWN

        return FailureReport(
            kind=kind,
            fault=fault,
            detail=str(error)[:300],
            retryable=(fault == FaultClass.TRANSIENT),
        )

    @staticmethod
    def is_retryable(report: FailureReport) -> bool:
        """仅 TRANSIENT 可自动重试；HITL 超时/永久错误不重试。"""
        return report.fault == FaultClass.TRANSIENT

    @staticmethod
    def needs_human(report: FailureReport) -> bool:
        """HITL 超时/人工类异常需人工介入。"""
        return report.fault == FaultClass.HUMAN
