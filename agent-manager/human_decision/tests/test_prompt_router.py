# -*- coding: utf-8 -*-
"""UserPromptSubmit 路由：HITL 消息阻止普通 Agent，普通聊天放行。"""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PARENT = os.path.dirname(_PKG)
sys.path[:0] = [_PARENT, _PKG]

from human_decision.models import DecisionStatus  # noqa: E402
from human_decision.prompt_router import route_prompt  # noqa: E402

UID = "17248148409976157"
KEY = "dingtalk:d:cidSMSg0KkgNzAaeL1GcWcR8dGpepImrpvAWt9tJA3q9CU=:" + UID


@pytest.fixture(autouse=True)
def _decider(cfg):
    cfg.deciders = [{"user_id": UID, "name": "测试决策人"}]


def _mk(manager, task="3442"):
    return manager.create_decision(
        task_id=task, question="选哪个方案？",
        options=[{"id": "A", "description": "A"}, {"id": "B", "description": "B"},
                 {"id": "C", "description": "C"}],
        project_key="jeebootx",
    )


def _bind(store, rec, key=KEY):
    store.update_fields(rec.decision_id, cc_session_key=key)
    return rec


def test_no_pending_lets_normal_chat_through(manager):
    block, _ = route_prompt("A", KEY, UID, manager=manager)
    assert block is False


def test_single_pending_bare_option_blocks_agent(manager, store):
    rec = _bind(store, _mk(manager))
    block, msg = route_prompt("A", KEY, UID, manager=manager, msg_id="m1")
    assert block is True
    assert rec.decision_id in msg
    assert store.get(rec.decision_id).reply_choice == "A"


def test_single_pending_normal_chat_allowed(manager, store):
    rec = _bind(store, _mk(manager))
    block, _ = route_prompt("你好，今天做什么", KEY, UID, manager=manager, msg_id="m2")
    assert block is False
    assert store.get(rec.decision_id).status == DecisionStatus.WAITING_REPLY


def test_multiple_pending_bare_option_blocks_with_ids(manager, store):
    a = _bind(store, _mk(manager, task="3442"))
    b = _bind(store, _mk(manager, task="3657"))
    block, msg = route_prompt("B", KEY, UID, manager=manager, msg_id="m3")
    assert block is True
    assert a.decision_id in msg and b.decision_id in msg
    assert store.get(a.decision_id).status == DecisionStatus.WAITING_REPLY
    assert store.get(b.decision_id).status == DecisionStatus.WAITING_REPLY


def test_explicit_dec_id_custom_comment_blocks_and_accepts(manager, store):
    rec = _bind(store, _mk(manager))
    block, _ = route_prompt(f"{rec.decision_id} C 自定义意见", KEY, UID,
                            manager=manager, msg_id="m4")
    assert block is True
    got = store.get(rec.decision_id)
    assert got.reply_choice == "C"
    assert got.reply_comment == "自定义意见"


def test_other_chat_bare_option_not_claimed(manager, store):
    rec = _bind(store, _mk(manager), key="dingtalk:d:cidOTHER:" + UID)
    block, _ = route_prompt("A", KEY, UID, manager=manager, msg_id="m5")
    assert block is False
    assert store.get(rec.decision_id).status == DecisionStatus.WAITING_REPLY


def test_other_chat_explicit_id_blocks_and_rejects(manager, store):
    rec = _bind(store, _mk(manager), key="dingtalk:d:cidOTHER:" + UID)
    block, msg = route_prompt(f"{rec.decision_id} A", KEY, UID,
                              manager=manager, msg_id="m6")
    assert block is True
    assert "其他会话" in msg
    assert store.get(rec.decision_id).status == DecisionStatus.WAITING_REPLY


def test_invalid_choice_blocks_agent(manager, store):
    rec = _bind(store, _mk(manager))
    block, msg = route_prompt("X", KEY, UID, manager=manager, msg_id="m7")
    assert block is True
    assert "无效选项" in msg
    assert store.get(rec.decision_id).status == DecisionStatus.WAITING_REPLY
