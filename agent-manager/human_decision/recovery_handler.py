# -*- coding: utf-8 -*-
"""HITL — Recovery Handler：进程/Runner 重启后的对账恢复。

保证：
    - 从持久化存储恢复 WAITING_* 状态（决策不丢）
    - 不重复创建决策
    - 不丢失原 Session ID（session_id/cc 绑定在决策记录内）
    - 收到用户回复后仍能恢复执行（reply_handler + session_resumer 照常工作）
    - 通知失败的决策补发通知
"""
from __future__ import annotations

import os
import sys
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from human_decision.hitl_config import HitlConfig  # noqa: E402
from human_decision.models import DecisionStatus, _now  # noqa: E402
from human_decision.timeout_handler import check_timeouts  # noqa: E402


def recover(store, cfg: HitlConfig, notifier, *, logger=None) -> dict:
    """启动对账。返回 {restored, renotified, timeouts}。"""
    log = logger or (lambda m: None)
    restored, renotified = [], []

    for rec in store.list_waiting():
        restored.append(rec.decision_id)
        store.log_event(rec.decision_id, "recovered", {"status": rec.status.value, "at": _now()})

        # 通知从未成功 → 补发（决策继续等待，绝不放行）
        if rec.status in (DecisionStatus.CREATED, DecisionStatus.NOTIFY_FAILED):
            res = notifier.send_decision_request(rec)
            if res.get("sent"):
                store.transition(rec.decision_id, DecisionStatus.WAITING_REPLY,
                                 allowed_from={DecisionStatus.CREATED, DecisionStatus.NOTIFY_FAILED},
                                 fields={"notified_at": _now()})
                renotified.append(rec.decision_id)
            else:
                store.transition(rec.decision_id, DecisionStatus.NOTIFY_FAILED,
                                 allowed_from={DecisionStatus.CREATED, DecisionStatus.NOTIFY_FAILED},
                                 fields={"last_error": res.get("error", "")[:300]})
                log(f"补发通知失败 {rec.decision_id}: {res.get('error')}")

    # 顺带做一次超时扫描
    t = check_timeouts(store, cfg, notifier, logger=logger)
    return {"restored": restored, "renotified": renotified,
            "timeouts": t.get("timed_out", []), "reminded": t.get("reminded", [])}
