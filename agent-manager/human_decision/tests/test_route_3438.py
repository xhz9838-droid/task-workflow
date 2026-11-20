# -*- coding: utf-8 -*-
"""禅道 #3438 决策路由回归（场景 A / B）。

场景 A：存在 L2 决策、无 L3 → 自动决策，不创建 HITL。
场景 B：存在 L3 → 创建人工决策、任务 WAITING_HUMAN、发送通知；决策完成后任务恢复 RUNNING。
"""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PARENT = os.path.dirname(_PKG)
for _p in (_PKG, _PARENT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human_decision.mcp_server import install_task_state_hook  # noqa: E402
from human_decision.models import DecisionStatus  # noqa: E402
from human_decision.routing import route_decision  # noqa: E402
from models import ExecutionRun, TaskLevel, TaskState  # noqa: E402
from state_manager import StateManager  # noqa: E402


def _exec(db, task="3438", status=TaskState.RUNNING):
    sm = StateManager(db)
    eid = sm.create_execution(ExecutionRun(
        project_key="jeebootx", task_id=task, task_level=TaskLevel.M,
        workflow_status=status, current_stage="design"))
    sm.close()
    return eid


def _status(db, eid):
    sm = StateManager(db)
    try:
        for e in sm.list_executions():
            if e["id"] == eid:
                return e["workflow_status"]
    finally:
        sm.close()
    return None


# --------------------------------------------------------------- 场景 A：L2 自动
def test_scenario_a_l2_is_auto_and_not_hitl(manager, store):
    assert route_decision("L2")["route"] == "auto"
    assert route_decision("L2")["record_required"] is True
    assert route_decision("L1")["route"] == "auto"

    # 两个 L2 决策都不得创建人工决策
    for q in ("开关控件形态", "新增默认值"):
        with pytest.raises(ValueError):
            manager.create_decision(task_id="3438", question=q, level="L2")
    assert store.list(task_id="3438") == []


# --------------------------------------------------------------- 场景 B：L3 HITL
def test_scenario_b_l3_waits_human_and_resumes(manager, store, notifier, handler, tmp_path):
    db = str(tmp_path / "state.db")
    eid = _exec(db)
    install_task_state_hook(manager, db)

    rec = manager.create_decision(
        task_id="3438", question="需要变更 DDL，是否执行？", level="L3",
        options=[{"id": "A", "description": "批准"}, {"id": "B", "description": "驳回"}],
        project_key="jeebootx")

    # 通知已发送、任务进入 WAITING_HUMAN
    assert any(kind == "decision_request" for kind, _ in notifier.sent)
    assert _status(db, eid) == "WAITING_HUMAN"

    # 用户回复 A → 决策闭环 → 任务恢复 RUNNING
    r = handler.handle(raw_text="A", source="test", user_id="u1",
                       chat_session_key=rec.cc_session_key or "")
    assert r["outcome"] == "accepted"
    assert manager.complete(rec.decision_id) is True
    assert _status(db, eid) == "RUNNING"
    assert store.get(rec.decision_id).status == DecisionStatus.COMPLETED
