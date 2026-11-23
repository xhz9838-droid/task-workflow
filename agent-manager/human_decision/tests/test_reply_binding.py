# -*- coding: utf-8 -*-
"""HITL 回复绑定回归：未绑定决策、串会话、自动绑定、超时后迟到回复。

事故背景：DEC-3442-16301801 创建时没有 CC_SESSION_KEY，用户钉钉回复 "B" 被
watch 识别后错误落到另一个已 RESUMED 的决策，导致原决策一直 WAITING_REPLY。
"""
from __future__ import annotations

import json
import os

import pytest

from human_decision.models import DecisionStatus, ResumeMethod

UID = "17248148409976157"
KEY = "dingtalk:d:cidSMSg0KkgNzAaeL1GcWcR8dGpepImrpvAWt9tJA3q9CU=:" + UID


@pytest.fixture(autouse=True)
def _decider(cfg):
    cfg.deciders = [{"user_id": UID, "name": "测试决策人"}]


def _iso(minutes_ago: int = 0) -> str:
    import datetime as _dt
    return (_dt.datetime.now().astimezone()
            - _dt.timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


def _mk(manager, task="3442"):
    return manager.create_decision(
        task_id=task, question="选哪个方案？",
        options=[{"id": "A", "description": "A"}, {"id": "B", "description": "B"}],
        project_key="jeebootx",
    )


def test_discover_chat_binding_prefers_configured_user(cfg):
    sdir = cfg.sessions_dir()
    os.makedirs(sdir, exist_ok=True)
    other = "dingtalk:d:cidOther:999"
    with open(os.path.join(sdir, "personal_1.json"), "w", encoding="utf-8") as f:
        json.dump({"active_session": {other: "s1"}}, f)
    with open(os.path.join(sdir, "personal_2.json"), "w", encoding="utf-8") as f:
        json.dump({"active_session": {KEY: "s1"}}, f)
    cfg.dingtalk_user_id = UID
    project, key = cfg.discover_chat_binding()
    assert project == "personal"
    assert key == KEY
    assert cfg.project_for_session_key(KEY) == "personal"


def test_discover_chat_binding_does_not_guess_without_user(cfg):
    sdir = cfg.sessions_dir()
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, "personal_1.json"), "w", encoding="utf-8") as f:
        json.dump({"active_session": {KEY: "s1"}}, f)
    cfg.dingtalk_user_id = ""
    cfg.deciders = []
    assert cfg.discover_chat_binding() == ("", "")


def test_create_decision_binds_default_chat_without_env(cfg, manager, store):
    sdir = cfg.sessions_dir()
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, "personal_1.json"), "w", encoding="utf-8") as f:
        json.dump({"active_session": {KEY: "s1"}}, f)
    cfg.dingtalk_user_id = UID

    rec = _mk(manager)
    got = store.get(rec.decision_id)
    assert got.cc_session_key == KEY          # 无 CC_* 环境也能绑定
    assert got.cc_project == "personal"
    assert any(e["event"] == "binding_auto" for e in store.events(rec.decision_id))


def test_unbound_reply_binds_single_waiting_decision(handler, store, manager):
    rec = _mk(manager)
    r = handler.handle(raw_text="B", source="watch", user_id=UID,
                       chat_session_key=KEY, msg_id="m-single", msg_ts=_iso())
    assert r["outcome"] == "accepted"
    assert r["decision_id"] == rec.decision_id
    got = store.get(rec.decision_id)
    assert got.reply_choice == "B"
    assert got.cc_session_key == KEY
    assert store.replies(rec.decision_id)[0]["accepted"] == 1


def test_reply_does_not_misroute_to_resumed_decision(handler, store, manager):
    """复现事故：同聊天有已 RESUMED 决策 + 新的未绑定待决决策。"""
    old = _mk(manager, task="3413")
    r0 = handler.handle(raw_text="A", source="watch", user_id=UID,
                        chat_session_key=KEY, msg_id="m-old", msg_ts=_iso())
    assert r0["outcome"] == "accepted"
    assert store.get(old.decision_id).status in (DecisionStatus.RESUMED,
                                                 DecisionStatus.RESUME_FAILED)

    new = _mk(manager, task="3442")
    r = handler.handle(raw_text="B", source="watch", user_id=UID,
                       chat_session_key=KEY, msg_id="m-new", msg_ts=_iso())
    assert r["outcome"] == "accepted"
    assert r["decision_id"] == new.decision_id
    assert store.get(new.decision_id).reply_choice == "B"
    # 旧决策不被写入第二次回复
    assert len(store.replies(old.decision_id)) == 1


def test_latest_unbound_decision_wins_with_clear_time_gap(handler, store, manager):
    older = _mk(manager, task="3657")
    newer = _mk(manager, task="3442")
    store.update_fields(older.decision_id, notified_at=_iso(24 * 60))
    store.update_fields(newer.decision_id, notified_at=_iso(1))

    r = handler.handle(raw_text="B", source="watch", user_id=UID,
                       chat_session_key=KEY, msg_id="m-gap", msg_ts=_iso())
    assert r["outcome"] == "accepted"
    assert r["decision_id"] == newer.decision_id
    assert store.get(older.decision_id).status in (
        DecisionStatus.CREATED, DecisionStatus.NOTIFIED, DecisionStatus.WAITING_REPLY)


def test_reminder_does_not_steal_reply_from_newer_decision(handler, store, manager):
    """旧决策的提醒时间晚于新决策通知时，仍应匹配新决策（事故同型）。"""
    older = _mk(manager, task="3657")
    newer = _mk(manager, task="3442")
    store.update_fields(older.decision_id,
                        notified_at=_iso(24 * 60), reminded_at=_iso(1))
    store.update_fields(newer.decision_id, notified_at=_iso(2))

    r = handler.handle(raw_text="B", source="watch", user_id=UID,
                       chat_session_key=KEY, msg_id="m-reminded", msg_ts=_iso())
    assert r["outcome"] == "accepted"
    assert r["decision_id"] == newer.decision_id


def test_close_notifications_require_explicit_decision_id(handler, store, manager):
    a = _mk(manager, task="3443")
    b = _mk(manager, task="3444")
    store.update_fields(a.decision_id, notified_at=_iso(1))
    store.update_fields(b.decision_id, notified_at=_iso(1))

    r = handler.handle(raw_text="B", source="watch", user_id=UID,
                       chat_session_key=KEY, msg_id="m-amb", msg_ts=_iso())
    assert r["outcome"] == "unmatched"
    assert "多个待决决策" in r["reason"]
    assert any(e["event"] == "reply_unmatched" for e in store.events(""))

    r2 = handler.handle(raw_text=f"{b.decision_id} B", source="watch", user_id=UID,
                        chat_session_key=KEY, msg_id="m-explicit", msg_ts=_iso())
    assert r2["outcome"] == "accepted"
    assert r2["decision_id"] == b.decision_id


def test_default_resume_packet_uses_workflow_root(manager, store, monkeypatch, tmp_path):
    """未配置 execution_root 时，恢复包必须落在工作流根 execution/ 下，而非上级目录。"""
    from human_decision import session_resumer

    monkeypatch.setattr(session_resumer, "_ROOT", str(tmp_path))
    manager.cfg.execution_root = ""
    rec = _mk(manager)
    path = manager.resumer.write_resume_packet(store.get(rec.decision_id))
    assert os.path.abspath(path).startswith(
        os.path.join(os.path.abspath(str(tmp_path)), "execution"))


def test_stale_unbound_decision_not_auto_claimed(handler, store, manager):
    """超过 12h 的未绑定决策不自动认领，避免过期决策吞掉新回复。"""
    stale = _mk(manager, task="3657")
    store.update_fields(stale.decision_id, notified_at=_iso(24 * 60))

    r = handler.handle(raw_text="B", source="watch", user_id=UID,
                       chat_session_key=KEY, msg_id="m-stale", msg_ts=_iso())
    assert r["outcome"] == "unmatched"
    assert store.get(stale.decision_id).status == DecisionStatus.WAITING_REPLY


def test_stale_decision_still_accepts_explicit_id(handler, store, manager):
    stale = _mk(manager, task="3657")
    store.update_fields(stale.decision_id, notified_at=_iso(24 * 60))
    r = handler.handle(raw_text=f"{stale.decision_id} B", source="watch", user_id=UID,
                       chat_session_key=KEY, msg_id="m-stale-id", msg_ts=_iso())
    assert r["outcome"] == "accepted"
    assert r["decision_id"] == stale.decision_id


def test_manual_decision_without_tool_wait_uses_checkpoint(handler, store, manager):
    """手工/CLI 创建的决策没有 tool_waiting，不能虚报 live_continue。"""
    rec = _mk(manager)
    r = handler.handle(raw_text="B", source="watch", user_id=UID,
                       chat_session_key=KEY, msg_id="m-no-wait", msg_ts=_iso())
    assert r["outcome"] == "accepted"
    got = store.get(rec.decision_id)
    assert got.resume_method == ResumeMethod.CHECKPOINT_REBUILD


def test_late_reply_after_suspend_is_accepted(handler, store, manager):
    rec = _mk(manager)
    wait = manager.wait_for_decision(rec.decision_id, wait_seconds=0.2)
    assert wait["outcome"] == "suspended"
    assert store.get(rec.decision_id).status == DecisionStatus.WAITING_REPLY

    r = handler.handle(raw_text="B", source="watch", user_id=UID,
                       chat_session_key=KEY, msg_id="m-late", msg_ts=_iso())
    assert r["outcome"] == "accepted"
    got = store.get(rec.decision_id)
    assert got.reply_choice == "B"
    assert got.status in (DecisionStatus.RESUMED, DecisionStatus.RESUME_FAILED)
