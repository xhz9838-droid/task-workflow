# -*- coding: utf-8 -*-
"""单元测试：Session Resumer 恢复策略与检查点包。"""
from __future__ import annotations

import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from human_decision.models import DecisionStatus, ResumeMethod
from conftest import make_record


def _decided(store, decision_id="DEC-R1-001"):
    rec = make_record(store, decision_id=decision_id)
    store.transition(rec.decision_id, DecisionStatus.WAITING_REPLY,
                     allowed_from={DecisionStatus.CREATED})
    store.transition(rec.decision_id, DecisionStatus.DECISION_RECEIVED,
                     allowed_from={DecisionStatus.WAITING_REPLY},
                     fields={"reply_choice": "A", "reply_comment": "走方案A",
                             "reply_user_name": "测试", "user_reply": "A"})
    return store.get(decision_id)


def test_resume_live_continue_when_tool_waiting(resumer, store):
    rec = _decided(store)
    out = resumer.resume(rec)
    assert out["resume_method"] == ResumeMethod.LIVE_CONTINUE.value
    got = store.get(rec.decision_id)
    assert got.status == DecisionStatus.RESUMED


def test_resume_checkpoint_when_tool_suspended(resumer, store):
    rec = _decided(store)
    store.log_event(rec.decision_id, "tool_suspended", {})
    out = resumer.resume(rec)
    # 测试环境无 cc-connect → 检查点重建
    assert out["resume_method"] == ResumeMethod.CHECKPOINT_REBUILD.value
    packet = os.path.join(resumer.cfg.execution_root, rec.project_key, rec.task_id,
                          "human-decision", f"resume-packet-{rec.decision_id}.md")
    assert os.path.exists(packet)
    content = open(packet, encoding="utf-8").read()
    assert rec.decision_id in content and "方案A" in content or "走方案A" in content
    jpath = packet.replace(f"resume-packet-{rec.decision_id}.md",
                           f"decision-{rec.decision_id}.json")
    assert os.path.exists(jpath)


def test_resume_live_inject_when_session_live(resumer, store, monkeypatch):
    rec = _decided(store)
    store.log_event(rec.decision_id, "tool_suspended", {})
    injected = []
    monkeypatch.setattr(type(resumer), "_session_live", lambda self, p, k, *a: True)
    monkeypatch.setattr(type(resumer), "_try_live_inject",
                        lambda self, r: injected.append(1) or True)
    out = resumer.resume(rec)
    assert out["resume_method"] == ResumeMethod.LIVE_CONTINUE.value
    assert injected == [1]


def test_resume_idempotent(resumer, store):
    rec = _decided(store)
    resumer.resume(rec)
    out2 = resumer.resume(rec)  # 并发/重复触发
    assert "already" in out2.get("detail", "") or out2.get("resume_method")
    assert store.get(rec.decision_id).status == DecisionStatus.RESUMED
