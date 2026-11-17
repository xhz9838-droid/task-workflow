# -*- coding: utf-8 -*-
"""HITL 测试公共 fixture。"""
from __future__ import annotations

import os
import sys
import datetime

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)          # human_decision/
_PARENT = os.path.dirname(_PKG)        # agent-manager/
for _p in (_PARENT, _PKG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human_decision.decision_store import DecisionStore  # noqa: E402
from human_decision.hitl_config import HitlConfig  # noqa: E402
from human_decision.decision_manager import DecisionManager  # noqa: E402
from human_decision.reply_handler import ReplyHandler  # noqa: E402
from human_decision.session_resumer import SessionResumer  # noqa: E402
from human_decision.models import DecisionOption, DecisionRecord, DecisionLevel  # noqa: E402


class FakeNotifier:
    """记录所有通知，不真正发送。"""

    def __init__(self):
        self.sent = []
        self.fail = False

    def send_decision_request(self, rec):
        if self.fail:
            return {"sent": False, "attempts": 3, "error": "fake failure"}
        self.sent.append(("decision_request", rec.decision_id))
        return {"sent": True, "attempts": 1, "error": ""}

    def send_text(self, body, **kw):
        if self.fail:
            return {"sent": False, "error": "fake failure"}
        self.sent.append(("text", body[:60]))
        return {"sent": True, "error": ""}

    def send_reminder(self, rec):
        self.sent.append(("reminder", rec.decision_id))
        return {"sent": True, "error": ""}

    def send_timeout_notice(self, rec):
        self.sent.append(("timeout_notice", rec.decision_id))
        return {"sent": True, "error": ""}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """测试不继承 cc-connect 会话环境，也不写真实审计/execution 树。"""
    for var in ("CC_PROJECT", "CC_SESSION_KEY", "CC_MGMT_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HITL_NO_AUDIT", "1")
    from human_decision import reply_handler as rh

    rh.ReplyHandler._seen_cache = set()
    yield


@pytest.fixture
def cfg(tmp_path):
    c = HitlConfig(
        dry_run_notify=True,
        watch_session_files=True,
        cc_data_dir=str(tmp_path / "ccdata"),
        execution_root=str(tmp_path / "execution"),
        tool_wait_seconds=2,
        poll_interval_seconds=0.05,
        notify_retries=1,
        notify_retry_interval_seconds=0,
        remind_after_seconds=3600,
        timeout_after_seconds=7200,
    )
    os.makedirs(c.sessions_dir(), exist_ok=True)
    return c


@pytest.fixture
def store(tmp_path):
    s = DecisionStore(db_path=str(tmp_path / "test.db"))
    yield s
    s.close()


@pytest.fixture
def notifier():
    return FakeNotifier()


@pytest.fixture
def resumer(cfg, store):
    return SessionResumer(cfg, store)


@pytest.fixture
def handler(cfg, store, notifier, resumer):
    return ReplyHandler(cfg, store, resumer, notifier)


@pytest.fixture
def manager(cfg, store, notifier, resumer):
    return DecisionManager(cfg, store, notifier, resumer)


def make_record(store, **kw) -> DecisionRecord:
    rec = DecisionRecord(
        decision_id=kw.get("decision_id", "DEC-T1-001"),
        task_id=kw.get("task_id", "T1"),
        level=kw.get("level", DecisionLevel.P1),
        question=kw.get("question", "选哪个方案？"),
        options=kw.get("options", [DecisionOption("A", "方案A"), DecisionOption("B", "方案B")]),
        recommended_option=kw.get("recommended_option", "A"),
        project_key=kw.get("project_key", "demo"),
        cc_session_key=kw.get("cc_session_key", "dingtalk:d:cidX:100000000000000001"),
        cc_project=kw.get("cc_project", "personal"),
    )
    store.create(rec)
    return rec


def now_minus(seconds: float) -> str:
    t = datetime.datetime.now().astimezone() - datetime.timedelta(seconds=seconds)
    return t.isoformat(timespec="seconds")
