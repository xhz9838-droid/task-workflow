# -*- coding: utf-8 -*-
"""T06 桥接测试：task_state_hook 生产接线（决策状态 ↔ agent-manager 任务状态）。

覆盖：
    1. 决策创建 → 任务 WAITING_HUMAN（真实 execution 记录被更新 + 事件留痕）
    2. 决策闭环 complete → 任务 RUNNING（恢复执行）
    3. 无对应执行记录（独立测试任务）→ 静默跳过，不抛异常
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)          # human_decision/
_PARENT = os.path.dirname(_PKG)        # agent-manager/
# 顺序：_PARENT 先于 _PKG，保证裸模块名 `models`/`cli` 解析到 agent-manager 侧
for _p in (_PKG, _PARENT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human_decision.mcp_server import install_task_state_hook, load_state_manager  # noqa: E402

_sm = load_state_manager()  # 消解 models 同名歧义后导入
StateManager = _sm.StateManager
ExecutionRun = _sm.ExecutionRun
TaskState = _sm.TaskState
from models import TaskLevel  # noqa: E402  （load_state_manager 已解析到 agent-manager 侧）


def _make_execution(db_path: str, project_key: str, task_id: str) -> int:
    sm = StateManager(db_path)
    try:
        return sm.create_execution(ExecutionRun(
            project_key=project_key, task_id=task_id,
            task_level=TaskLevel.S, workflow_status=TaskState.RUNNING,
            current_stage="routing",
        ))
    finally:
        sm.close()


def _execution_status(db_path: str, eid: int) -> str:
    sm = StateManager(db_path)
    try:
        for e in sm.list_executions():
            if e["id"] == eid:
                return str(e.get("workflow_status", ""))
        return "<missing>"
    finally:
        sm.close()


def _events(db_path: str, eid: int) -> list[dict]:
    sm = StateManager(db_path)
    try:
        return sm.get_events(eid)
    finally:
        sm.close()


def test_decision_create_sets_waiting_human(manager, tmp_path):
    # Arrange
    db = str(tmp_path / "am.db")
    eid = _make_execution(db, "hitl-e2e", "HITL-A02-T")
    install_task_state_hook(manager, db_path=db)

    # Act
    rec = manager.create_decision(
        task_id="HITL-A02-T", question="桥接测试：请选择",
        options=[{"id": "A", "description": "方案A"}],
        project_key="hitl-e2e", level="P1",
    )

    # Assert
    assert _execution_status(db, eid) == "WAITING_HUMAN"
    evs = _events(db, eid)
    assert any(e.get("event_type") == "hitl_task_state"
               and (e.get("details") or {}).get("state") == "WAITING_HUMAN" for e in evs)
    assert rec.decision_id


def test_decision_complete_sets_running(manager, tmp_path):
    # Arrange
    db = str(tmp_path / "am.db")
    eid = _make_execution(db, "hitl-e2e", "HITL-A02-T2")
    install_task_state_hook(manager, db_path=db)
    rec = manager.create_decision(
        task_id="HITL-A02-T2", question="桥接测试2：请选择",
        options=[{"id": "A", "description": "方案A"}],
        project_key="hitl-e2e", level="P1",
    )
    assert _execution_status(db, eid) == "WAITING_HUMAN"

    # Arrange：决策已被回复并恢复（RESUMED）—— complete 仅允许从 RESUMED/REJECTED 闭环
    from human_decision.models import DecisionStatus
    ok = manager.store.transition(
        rec.decision_id, DecisionStatus.RESUMED,
        allowed_from={DecisionStatus.WAITING_REPLY}, fields={},
    )
    assert ok is True

    # Act
    ok = manager.complete(rec.decision_id)

    # Assert
    assert ok is True
    assert _execution_status(db, eid) == "RUNNING"


def test_no_execution_record_is_silent(manager, tmp_path):
    # Arrange：空状态库，无任何执行记录
    db = str(tmp_path / "am-empty.db")
    install_task_state_hook(manager, db_path=db)

    # Act / Assert：不抛异常即可
    manager._notify_task_state("NOT-REGISTERED", "WAITING_HUMAN", "DEC-X")
    manager._notify_task_state("NOT-REGISTERED", "RUNNING", "DEC-X")
