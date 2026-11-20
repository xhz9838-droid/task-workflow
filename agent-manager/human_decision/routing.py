# -*- coding: utf-8 -*-
"""决策路由策略：把 L1/L2/L3 与 P0/P1/P2 映射为 auto / hitl。

规则（与 references/approval-policy.md 一致）：
    L1 / P2  → auto（Agent 自主处理）
    L2       → auto + ADR（授权内自决，写入 decisions.md，不调用 HITL）
    L3 / P0  → hitl（必须人工决策）
    P1       → hitl（显式请求人工，或检测器建议）
"""
from __future__ import annotations

from human_decision.models import DecisionLevel


def route_decision(level: str | DecisionLevel) -> dict:
    raw = str(getattr(level, "value", level)).strip().upper()
    if raw in ("L3", "P0"):
        return {"route": "hitl", "level": "P0", "record_required": False,
                "reason": "L3/P0：重大决策，必须人工"}
    if raw == "L2":
        return {"route": "auto", "level": "P1", "record_required": True,
                "reason": "L2：授权内自决，写入 decisions.md（ADR），不调用 HITL"}
    if raw in ("L1", "P2"):
        return {"route": "auto", "level": "P2", "record_required": False,
                "reason": "L1/P2：常规问题，Agent 自主处理"}
    if raw == "P1":
        return {"route": "hitl", "level": "P1", "record_required": False,
                "reason": "P1：建议人工决策"}
    raise ValueError("未知决策等级：%r（支持 L1/L2/L3/P0/P1/P2）" % level)
