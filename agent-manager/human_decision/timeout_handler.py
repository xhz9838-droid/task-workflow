# -*- coding: utf-8 -*-
"""HITL — Timeout Handler：超时提醒与超时标记。

铁律：**超时不自动批准**。超过 remind_after → 发提醒；
超过 timeout_after → 标记 DECISION_TIMEOUT 并通知用户；
决策保持可回复状态，用户随时可继续回复（迟到回复仍生效）。
"""
from __future__ import annotations

import sys
import os
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from human_decision.hitl_config import HitlConfig  # noqa: E402
from human_decision.models import DecisionStatus, _now  # noqa: E402


def check_timeouts(store, cfg: HitlConfig, notifier, *, logger=None) -> dict:
    """扫描等待中的决策，发提醒 / 标记超时。返回处理摘要。"""
    log = logger or (lambda m: None)
    reminded, timed_out = [], []
    for rec in store.list_waiting():
        if rec.status == DecisionStatus.DECISION_TIMEOUT:
            continue  # 已超时，仅保留等待迟到回复
        now = _now()
        # 提醒
        if (
            rec.notified_at
            and cfg.remind_after_seconds > 0
            and not rec.reminded_at
            and _elapsed(rec.notified_at, now) >= cfg.remind_after_seconds
        ):
            try:
                notifier.send_reminder(rec)
            except Exception as e:
                log(f"提醒发送失败 {rec.decision_id}: {e}")
            store.update_fields(rec.decision_id, reminded_at=now)
            store.log_event(rec.decision_id, "reminded", {"at": now})
            reminded.append(rec.decision_id)

        # 超时标记（不自动批准）
        if (
            rec.notified_at
            and cfg.timeout_after_seconds > 0
            and _elapsed(rec.notified_at, now) >= cfg.timeout_after_seconds
        ):
            ok = store.transition(
                rec.decision_id, DecisionStatus.DECISION_TIMEOUT,
                allowed_from={DecisionStatus.CREATED, DecisionStatus.NOTIFY_FAILED,
                              DecisionStatus.NOTIFIED, DecisionStatus.WAITING_REPLY},
            )
            if ok:
                try:
                    notifier.send_timeout_notice(rec)
                except Exception as e:
                    log(f"超时通知失败 {rec.decision_id}: {e}")
                store.log_event(rec.decision_id, "timeout", {"at": now, "auto_approved": False})
                timed_out.append(rec.decision_id)
    return {"reminded": reminded, "timed_out": timed_out}


def _elapsed(from_ts: str, to_ts: str) -> float:
    import datetime as _dt

    def parse(t: str):
        try:
            return _dt.datetime.fromisoformat(t)
        except Exception:
            return None

    a, b = parse(from_ts), parse(to_ts)
    if not a or not b:
        return 0.0
    return max(0.0, (b - a).total_seconds())
