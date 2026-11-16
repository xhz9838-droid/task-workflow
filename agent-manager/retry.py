# -*- coding: utf-8 -*-
"""P11 Phase 2 — Retry：有限重试 + 故障分类。

策略（P11 §四.4）：
    - 默认最多 2 次，指数退避，有最大等待
    - 重试原因持久化，不覆盖旧失败日志

故障分类：
    TRANSIENT  可自动重试：网络抖动/超时/瞬时资源/可恢复启动失败
    PERMANENT  不盲目重试：代码错误/测试失败/ESLint/需求不明/缺依赖/权限不足
    HUMAN      停止：用户取消/业务决策/状态冲突/重复提交

代码错误应**交回 Main Agent 分析修复**，不是反复重启同一段代码。

重试前必须检查（P11 §四.4 末）：
    是否已有运行实例 / 是否已提交 / 是否已更新禅道 / 是否有未完成副作用 / 能否安全恢复。
"""
from __future__ import annotations

import datetime
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from .exceptions import (
        AgentManagerError,
        CodeError,
        DuplicateExecutionError,
        TaskLockError,
    )
    from .models import FaultClass
except ImportError:
    from exceptions import AgentManagerError, CodeError, DuplicateExecutionError, TaskLockError  # type: ignore
    from models import FaultClass  # type: ignore


# 故障 → 分类映射（供未显式标注 fault 的异常兜底）
FAULT_KEYWORDS: list[tuple[str, FaultClass]] = [
    # TRANSIENT
    ("timeout", FaultClass.TRANSIENT),
    ("timed out", FaultClass.TRANSIENT),
    ("connection reset", FaultClass.TRANSIENT),
    ("connection refused", FaultClass.TRANSIENT),
    ("temporarily unavailable", FaultClass.TRANSIENT),
    ("econnreset", FaultClass.TRANSIENT),
    ("etimedout", FaultClass.TRANSIENT),
    ("econnaborted", FaultClass.TRANSIENT),
    ("network", FaultClass.TRANSIENT),
    ("502", FaultClass.TRANSIENT),
    ("503", FaultClass.TRANSIENT),
    ("504", FaultClass.TRANSIENT),
    # PERMANENT
    ("syntaxerror", FaultClass.PERMANENT),
    ("typeerror", FaultClass.PERMANENT),
    ("assertionerror", FaultClass.PERMANENT),
    ("test failed", FaultClass.PERMANENT),
    ("eslint", FaultClass.PERMANENT),
    ("lint", FaultClass.PERMANENT),
    ("compile", FaultClass.PERMANENT),
    ("build failed", FaultClass.PERMANENT),
    ("modulenotfounderror", FaultClass.PERMANENT),
    ("importerror", FaultClass.PERMANENT),
    ("permission denied", FaultClass.PERMANENT),
    ("403", FaultClass.PERMANENT),
    ("401", FaultClass.PERMANENT),
    # HUMAN
    ("cancelled", FaultClass.HUMAN),
    ("canceled", FaultClass.HUMAN),
    ("duplicate", FaultClass.HUMAN),
    ("already running", FaultClass.HUMAN),
    ("business decision", FaultClass.HUMAN),
    ("human", FaultClass.HUMAN),
]


def classify_fault(error: BaseException | str) -> FaultClass:
    """异常/消息 → 故障分类。优先用异常自带 fault，否则按关键词兜底。"""
    if isinstance(error, AgentManagerError):
        return error.fault
    text = str(error).lower()
    for kw, fc in FAULT_KEYWORDS:
        if kw in text:
            return fc
    # 默认：不盲目重试（PERMANENT）
    return FaultClass.PERMANENT


@dataclass
class RetryRecord:
    """一次重试记录（持久化，不覆盖旧失败）"""

    attempt: int
    at: str
    fault_class: str
    reason: str
    action: str  # "retry" | "abort" | "hand_to_main"
    delay_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt,
            "at": self.at,
            "fault_class": self.fault_class,
            "reason": self.reason,
            "action": self.action,
            "delay_seconds": self.delay_seconds,
        }


@dataclass
class RetryPolicy:
    max_attempts: int = 2
    initial_delay_seconds: float = 30.0
    max_delay_seconds: float = 300.0
    exponential_backoff: bool = True

    @classmethod
    def from_config(cls, config: dict | None) -> "RetryPolicy":
        r = (config or {}).get("retry", {}) or {}
        return cls(
            max_attempts=int(r.get("max_attempts", 2)),
            initial_delay_seconds=float(r.get("initial_delay_seconds", 30)),
            max_delay_seconds=float(r.get("max_delay_seconds", 300)),
            exponential_backoff=bool(r.get("exponential_backoff", True)),
        )


class RetryManager:
    """有限重试执行器。"""

    def __init__(self, policy: RetryPolicy | None = None, *, sleep: Callable[[float], None] = time.sleep):
        self.policy = policy or RetryPolicy()
        self._sleep = sleep
        self.records: list[RetryRecord] = []

    def backoff_delay(self, attempt: int) -> float:
        """指数退避。attempt 从 1 开始。"""
        if not self.policy.exponential_backoff:
            d = self.policy.initial_delay_seconds
        else:
            d = self.policy.initial_delay_seconds * (2 ** max(0, attempt - 1))
        return min(d, self.policy.max_delay_seconds)

    def decide(
        self,
        *,
        attempt: int,
        error: BaseException | str,
        precheck: Optional[dict] = None,
    ) -> tuple[str, float, RetryRecord]:
        """决定重试/中止/交回主 Agent。

        返回 (action, delay_seconds, record)
            action: "retry" | "abort" | "hand_to_main"

        precheck（可选，P11 §四.4 末的安全检查）：
            {"already_running": bool, "already_committed": bool,
             "already_written_zentao": bool, "has_side_effects": bool}
        """
        fault = classify_fault(error)
        reason = str(error)[:300]
        now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")

        # 0) 副作用安全检查 —— 有副作用未确认则不盲目重试
        if precheck:
            dangerous = (
                precheck.get("already_committed")
                or precheck.get("already_written_zentao")
                or precheck.get("has_side_effects")
            )
            if dangerous:
                rec = RetryRecord(
                    attempt=attempt,
                    at=now,
                    fault_class=fault.value,
                    reason=f"存在未确认副作用({reason})，禁止盲目重试",
                    action="hand_to_main",
                )
                self.records.append(rec)
                return "hand_to_main", 0.0, rec

        # 1) HUMAN：停止
        if fault == FaultClass.HUMAN:
            rec = RetryRecord(attempt, now, fault.value, reason, "abort")
            self.records.append(rec)
            return "abort", 0.0, rec

        # 2) PERMANENT：交回 Main Agent，不重启同一段代码
        if fault == FaultClass.PERMANENT:
            rec = RetryRecord(
                attempt, now, fault.value,
                f"永久性错误，交回 Main Agent 分析修复（不盲目重试）: {reason}",
                "hand_to_main",
            )
            self.records.append(rec)
            return "hand_to_main", 0.0, rec

        # 3) TRANSIENT：检查是否超上限
        if attempt > self.policy.max_attempts:
            rec = RetryRecord(
                attempt, now, fault.value,
                f"已达重试上限 {self.policy.max_attempts}（{reason}）",
                "abort",
            )
            self.records.append(rec)
            return "abort", 0.0, rec

        delay = self.backoff_delay(attempt)
        rec = RetryRecord(attempt, now, fault.value, reason, "retry", delay)
        self.records.append(rec)
        return "retry", delay, rec

    def run(
        self,
        fn: Callable[[], Any],
        *,
        precheck: Optional[Callable[[], dict]] = None,
        on_retry: Optional[Callable[[RetryRecord], None]] = None,
        max_attempts: Optional[int] = None,
    ) -> Any:
        """执行 fn，按分类自动重试。永久/人工错误直接抛出。"""
        limit = max_attempts or self.policy.max_attempts
        attempt = 1
        while True:
            try:
                return fn()
            except Exception as e:
                pc = precheck() if precheck else None
                action, delay, rec = self.decide(attempt=attempt, error=e, precheck=pc)
                if on_retry:
                    on_retry(rec)
                if action == "retry" and attempt <= limit:
                    if delay > 0:
                        self._sleep(delay)
                    attempt += 1
                    continue
                if action == "hand_to_main":
                    raise CodeError(
                        f"需要 Main Agent 分析修复（非自动重试）: {e}"
                    ) from e
                raise

    def stats(self) -> dict:
        by_action: dict[str, int] = {}
        for r in self.records:
            by_action[r.action] = by_action.get(r.action, 0) + 1
        return {
            "total_decisions": len(self.records),
            "by_action": by_action,
            "attempts_used": max((r.attempt for r in self.records), default=0),
        }
