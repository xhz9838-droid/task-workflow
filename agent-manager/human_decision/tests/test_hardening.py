# -*- coding: utf-8 -*-
"""HITL 加固回归测试：
    - L1/L2/L3 ↔ P0/P1/P2 映射，显式等级不得降级 P0
    - 配置决策人白名单后，CLI 空 user_id 不得绕过授权
    - 崩溃残留在 DECISION_RECEIVED / RESUMING 后可被 recover 回收
"""
from __future__ import annotations

from human_decision.decision_detector import detect
from human_decision.models import DecisionLevel, DecisionStatus


# --------------------------------------------------------------- 分级映射
def test_explicit_l3_maps_to_p0():
    r = detect(question="普通问题", explicit_level="L3")
    assert r.level == DecisionLevel.P0


def test_explicit_l2_maps_to_p1():
    r = detect(question="普通问题", explicit_level="L2")
    assert r.level == DecisionLevel.P1


def test_explicit_p2_cannot_downgrade_p0():
    r = detect(question="修改表结构并删除数据", explicit_level="P2")
    assert r.level == DecisionLevel.P0, r.reason


def test_explicit_p1_kept_when_no_risk():
    r = detect(question="普通问题", explicit_level="P1")
    assert r.level == DecisionLevel.P1


# --------------------------------------------------------------- 身份校验
def test_cli_empty_user_id_rejected_when_deciders_configured(handler, store, cfg):
    from conftest import make_record  # noqa: E402
    cfg.deciders = [{"user_id": "boss", "name": "老板"}]
    make_record(store)
    store.transition("DEC-T1-001", DecisionStatus.WAITING_REPLY,
                     allowed_from={DecisionStatus.CREATED})
    r = handler.handle(raw_text="A", source="cli", user_id="",
                       chat_session_key="dingtalk:d:cidX:100000000000000001")
    assert r["outcome"] == "rejected"
    assert store.get("DEC-T1-001").status == DecisionStatus.WAITING_REPLY


# --------------------------------------------------------------- 崩溃恢复
def test_recover_from_decision_received(manager, store, notifier):
    rec = manager.create_decision(task_id="T9", question="确认？",
                                  options=[{"id": "A", "description": "通过"}], level="P1")
    store.transition(rec.decision_id, DecisionStatus.DECISION_RECEIVED,
                     allowed_from={DecisionStatus.WAITING_REPLY})
    out = manager.recover()
    assert rec.decision_id in out["resumed_retried"]
    got = store.get(rec.decision_id)
    assert got.status in (DecisionStatus.RESUMING, DecisionStatus.RESUMED)


def test_recover_from_resuming(manager, store, notifier):
    rec = manager.create_decision(task_id="T10", question="确认？",
                                  options=[{"id": "A", "description": "通过"}], level="P1")
    store.transition(rec.decision_id, DecisionStatus.DECISION_RECEIVED,
                     allowed_from={DecisionStatus.WAITING_REPLY})
    store.transition(rec.decision_id, DecisionStatus.RESUMING,
                     allowed_from={DecisionStatus.DECISION_RECEIVED})
    out = manager.recover()
    assert rec.decision_id in out["resumed_retried"]
    assert store.get(rec.decision_id).status == DecisionStatus.RESUMED


def test_recover_from_resume_failed(manager, store, notifier):
    rec = manager.create_decision(task_id="T11", question="确认？",
                                  options=[{"id": "A", "description": "通过"}], level="P1")
    store.transition(rec.decision_id, DecisionStatus.DECISION_RECEIVED,
                     allowed_from={DecisionStatus.WAITING_REPLY})
    store.transition(rec.decision_id, DecisionStatus.RESUME_FAILED,
                     allowed_from={DecisionStatus.DECISION_RECEIVED})
    out = manager.recover()
    assert rec.decision_id in out["resumed_retried"]
    assert store.get(rec.decision_id).status == DecisionStatus.RESUMED
