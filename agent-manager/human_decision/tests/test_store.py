# -*- coding: utf-8 -*-
"""单元测试：DecisionStore 持久化与幂等。"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from human_decision.models import (
    DecisionLevel, DecisionStatus, ReplyKind, ReplyRecord,
)
from conftest import make_record


def test_create_and_get(store):
    rec = make_record(store)
    got = store.get(rec.decision_id)
    assert got is not None
    assert got.task_id == "T1"
    assert got.level == DecisionLevel.P1
    assert [o.id for o in got.options] == ["A", "B"]
    assert got.status == DecisionStatus.CREATED


def test_guarded_transition(store):
    rec = make_record(store)
    ok1 = store.transition(rec.decision_id, DecisionStatus.WAITING_REPLY,
                           allowed_from={DecisionStatus.CREATED})
    ok2 = store.transition(rec.decision_id, DecisionStatus.DECISION_RECEIVED,
                           allowed_from={DecisionStatus.CREATED})  # 已不是 CREATED
    assert ok1 and not ok2
    assert store.get(rec.decision_id).status == DecisionStatus.WAITING_REPLY


def test_reply_dedup_by_msg_id(store):
    rec = make_record(store)
    rep = ReplyRecord(decision_id=rec.decision_id, raw_text="A", source="test",
                      accepted=True, msg_id="m1", kind=ReplyKind.OPTION, parsed_choice="A")
    id1 = store.record_reply(rep)
    id2 = store.record_reply(rep)
    assert id1 is not None and id2 is None
    assert len(store.replies(rec.decision_id)) == 1


def test_list_waiting_and_events(store):
    rec = make_record(store)
    store.transition(rec.decision_id, DecisionStatus.WAITING_REPLY,
                     allowed_from={DecisionStatus.CREATED})
    make_record(store, decision_id="DEC-T2-001", task_id="T2")
    waiting = store.list_waiting()
    ids = {d.decision_id for d in waiting}
    assert rec.decision_id in ids          # WAITING_REPLY
    assert "DEC-T2-001" in ids             # CREATED
    evs = store.events(rec.decision_id)
    assert any(e["event"] == "created" for e in evs)
    assert any(e["event"] == "status" for e in evs)


def test_persistence_across_instances(tmp_path):
    from human_decision.decision_store import DecisionStore

    db = str(tmp_path / "p.db")
    s1 = DecisionStore(db_path=db)
    rec = make_record(s1)
    s1.close()
    s2 = DecisionStore(db_path=db)
    got = s2.get(rec.decision_id)
    assert got is not None and got.question == "选哪个方案？"
    s2.close()
