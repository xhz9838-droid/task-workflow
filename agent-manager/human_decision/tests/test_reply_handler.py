# -*- coding: utf-8 -*-
"""单元测试：回复处理（身份校验 / 幂等 / 串任务 / 无效回复 / STOP / 旧消息）。"""
from __future__ import annotations

import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from human_decision.models import DecisionStatus, ReplyKind
from conftest import make_record, now_minus


def _waiting(store, decision_id="DEC-T1-001", **kw):
    rec = make_record(store, decision_id=decision_id, **kw)
    store.transition(rec.decision_id, DecisionStatus.WAITING_REPLY,
                     allowed_from={DecisionStatus.CREATED})
    return store.get(rec.decision_id)


def test_accept_option_reply(handler, store):
    _waiting(store)
    r = handler.handle(raw_text="A", source="test", user_id="u1",
                       chat_session_key="dingtalk:d:cidX:17248148409976157")
    assert r["outcome"] == "accepted" and r["choice"] == "A"
    got = store.get("DEC-T1-001")
    assert got.status in (DecisionStatus.DECISION_RECEIVED, DecisionStatus.RESUMING,
                          DecisionStatus.RESUMED)
    assert got.reply_choice == "A" and got.reply_user_id == "u1"


def test_duplicate_reply_idempotent(handler, store):
    _waiting(store)
    key = "dingtalk:d:cidX:17248148409976157"
    r1 = handler.handle(raw_text="A", source="test", user_id="u1", chat_session_key=key)
    r2 = handler.handle(raw_text="B", source="test", user_id="u1", chat_session_key=key)
    assert r1["outcome"] == "accepted"
    assert r2["outcome"] == "duplicate"
    assert store.get("DEC-T1-001").reply_choice == "A"  # 第一次生效


def test_concurrent_same_msg_id(handler, store):
    _waiting(store)
    key = "dingtalk:d:cidX:17248148409976157"
    r1 = handler.handle(raw_text="A", source="hook", user_id="u1",
                        chat_session_key=key, msg_id="same")
    r2 = handler.handle(raw_text="A", source="watch", user_id="u1",
                        chat_session_key=key, msg_id="same")
    assert r1["outcome"] == "accepted"
    assert r2["outcome"] == "duplicate"


def test_invalid_option_rejected(handler, store):
    _waiting(store)
    r = handler.handle(raw_text="X", source="test", user_id="u1",
                       chat_session_key="dingtalk:d:cidX:17248148409976157")
    assert r["outcome"] == "invalid"
    assert store.get("DEC-T1-001").status == DecisionStatus.WAITING_REPLY  # 仍等待


def test_stop_reply(handler, store):
    _waiting(store)
    r = handler.handle(raw_text="STOP", source="test", user_id="u1",
                       chat_session_key="dingtalk:d:cidX:17248148409976157")
    assert r["outcome"] == "accepted" and r["choice"] == "STOP"
    assert store.get("DEC-T1-001").status == DecisionStatus.REJECTED


def test_unauthorized_user_rejected(handler, store, cfg):
    cfg.deciders = [{"user_id": "boss", "name": "老板"}]
    _waiting(store)
    r = handler.handle(raw_text="A", source="hook", user_id="intruder",
                       chat_session_key="dingtalk:d:cidX:17248148409976157")
    assert r["outcome"] == "rejected" and "身份" in r["reason"]
    assert store.get("DEC-T1-001").status == DecisionStatus.WAITING_REPLY  # 不放行


def test_authorized_decider_accepted(handler, store, cfg):
    cfg.deciders = [{"user_id": "boss", "name": "老板"}]
    _waiting(store)
    r = handler.handle(raw_text="A", source="hook", user_id="boss",
                       chat_session_key="dingtalk:d:cidX:17248148409976157")
    assert r["outcome"] == "accepted"


def test_group_reply_without_identity_rejected(handler, store, cfg):
    cfg.deciders = [{"user_id": "boss", "name": "老板"}]
    _waiting(store, cc_session_key="dingtalk:g:cidG:17248148409976157")
    r = handler.handle(raw_text="A", source="watch", user_id="",
                       chat_session_key="dingtalk:g:cidG:17248148409976157")
    assert r["outcome"] == "rejected"


def test_no_cross_task_mismatch(handler, store):
    """两个决策并行等待 → 裸回复不得串任务，要求显式 DEC-ID。"""
    _waiting(store, decision_id="DEC-T1-001", task_id="T1",
             cc_session_key="dingtalk:d:cidX:17248148409976157")
    _waiting(store, decision_id="DEC-T1-002", task_id="T1",
             cc_session_key="dingtalk:d:cidX:17248148409976157")
    r = handler.handle(raw_text="A", source="test", user_id="u1",
                       chat_session_key="dingtalk:d:cidX:17248148409976157")
    assert r["outcome"] == "unmatched"  # 歧义，不生效
    # 显式 DEC-ID 生效
    r2 = handler.handle(raw_text="DEC-T1-002 B", source="test", user_id="u1",
                        chat_session_key="dingtalk:d:cidX:17248148409976157")
    assert r2["outcome"] == "accepted" and r2["decision_id"] == "DEC-T1-002"
    assert store.get("DEC-T1-002").reply_choice == "B"
    assert store.get("DEC-T1-001").status == DecisionStatus.WAITING_REPLY


def test_other_chat_cannot_reply(handler, store):
    """决策绑定会话 A，来自会话 B 的裸回复不得命中。"""
    _waiting(store, cc_session_key="dingtalk:d:cidX:17248148409976157")
    r = handler.handle(raw_text="A", source="test", user_id="u1",
                       chat_session_key="dingtalk:d:cidOTHER:999")
    assert r["outcome"] == "unmatched"


def test_unknown_decision_id(handler, store):
    r = handler.handle(raw_text="DEC-NOPE-001 A", source="test", user_id="u1")
    assert r["outcome"] == "unmatched"


def test_watch_source_collect(handler, store, cfg):
    """会话文件轮询：新用户消息被识别为回复。"""
    _waiting(store, cc_session_key="dingtalk:d:cidX:17248148409976157")
    sess = {
        "sessions": {"s1": {"id": "s1", "agent_session_id": "sid-1", "agent_type": "claudecode",
                            "history": [
                                {"role": "user", "content": "开始任务", "timestamp": now_minus(3600)},
                                {"role": "assistant", "content": "好的", "timestamp": now_minus(3500)},
                                {"role": "user", "content": "DEC-T1-001 A", "timestamp": now_minus(1)},
                            ]}},
        "active_session": {"dingtalk:d:cidX:17248148409976157": "s1"},
        "user_meta": {"dingtalk:d:cidX:17248148409976157": {"user_name": "测试用户"}},
    }
    path = os.path.join(cfg.sessions_dir(), "personal_x.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sess, f, ensure_ascii=False)

    results = handler.collect_from_session_files()
    assert any(r.get("outcome") == "accepted" for r in results)
    got = store.get("DEC-T1-001")
    assert got.status in (DecisionStatus.DECISION_RECEIVED, DecisionStatus.RESUMING,
                          DecisionStatus.RESUMED)
    assert got.reply_user_id == "17248148409976157"  # 单聊从会话键取用户 ID

    # 再扫一次不重复处理
    results2 = handler.collect_from_session_files()
    assert all(r.get("outcome") != "accepted" for r in results2)


def test_watch_old_message_ignored(handler, store, cfg):
    """决策创建前的旧消息不得被误认为回复。"""
    rec = _waiting(store, cc_session_key="dingtalk:d:cidX:17248148409976157")
    sess = {
        "sessions": {"s1": {"id": "s1", "history": [
            {"role": "user", "content": "A", "timestamp": now_minus(7200)},  # 早于决策
        ]}},
        "active_session": {"dingtalk:d:cidX:17248148409976157": "s1"},
        "user_meta": {},
    }
    with open(os.path.join(cfg.sessions_dir(), "p.json"), "w", encoding="utf-8") as f:
        json.dump(sess, f)
    results = handler.collect_from_session_files()
    assert all(r.get("outcome") != "accepted" for r in results)
    assert store.get(rec.decision_id).status == DecisionStatus.WAITING_REPLY
