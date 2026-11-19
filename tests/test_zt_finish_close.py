# -*- coding: utf-8 -*-
"""zt.py finish/close 子命令测试（Mock 客户端，不访问真实禅道）。

覆盖：
- finish/close 幂等（已 done/closed 跳过）
- 关闭条件（禅道状态非 done → 暂缓并记录原因）
- 成功路径含读回核验与前后状态审计记录
- 读回失败、配置收紧（manual_only）拒绝
- finish 与 close 是两个独立流转
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import zt


class FakeFlowClient:
    """Mock ZenTaoClient：按序返回 task_detail 状态，记录流转调用。"""

    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = []

    def whoami(self):
        return {"profile": {"account": "me"}}

    def task_detail(self, task_id):
        s = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {"id": task_id, "status": s, "assignedTo": "me"}

    def task_finish(self, task_id, consumed, left, finishedDate, realStarted=None):
        self.calls.append(("finish", task_id, consumed, left, finishedDate, realStarted))
        return ({}, 200)

    def task_close(self, task_id, comment):
        self.calls.append(("close", task_id, comment))
        return ({}, 200)


def _finish_args(**over):
    kw = dict(task="3413", consumed=8.0, left=0.0, finishedDate="2026-11-20",
              realStarted=None, exec_id="E1")
    kw.update(over)
    return SimpleNamespace(**kw)


def _close_args(**over):
    kw = dict(task="3413", comment="交付完成，关闭", exec_id="E1")
    kw.update(over)
    return SimpleNamespace(**kw)


@pytest.fixture
def audit_rec(monkeypatch):
    rec = []
    monkeypatch.setattr(zt, "audit", lambda t, a, d=None, **k: rec.append((t, a, d or {})))
    return rec


def _use(monkeypatch, fake, mode="auto_after_gate"):
    monkeypatch.setattr(zt, "_client", lambda: fake)
    monkeypatch.setattr(zt, "_allow_mode", lambda path: mode)


# ------------------------------------------------------------- finish
def test_finish_success_readback(monkeypatch, audit_rec, capsys):
    fake = FakeFlowClient(["doing", "done"])
    _use(monkeypatch, fake)
    rc = zt.cmd_finish(_finish_args())
    assert rc == 0
    assert fake.calls == [("finish", "3413", 8.0, 0.0, "2026-11-20", None)]
    rec = [d for _, a, d in audit_rec if a == "zentao.finish"]
    assert rec and rec[-1]["result"] == "success"
    assert rec[-1]["before"] == "doing" and rec[-1]["after"] == "done"
    assert rec[-1]["exec_id"] == "E1"


def test_finish_idempotent_when_done(monkeypatch, audit_rec):
    fake = FakeFlowClient(["done"])
    _use(monkeypatch, fake)
    rc = zt.cmd_finish(_finish_args())
    assert rc == 0
    assert fake.calls == []  # 不重复流转
    rec = [d for _, a, d in audit_rec if a == "zentao.finish"]
    assert rec[-1]["result"] == "skipped_already_done"


def test_finish_rejects_non_doing(monkeypatch, audit_rec):
    fake = FakeFlowClient(["wait"])
    _use(monkeypatch, fake)
    rc = zt.cmd_finish(_finish_args())
    assert rc == 3
    assert fake.calls == []
    rec = [d for _, a, d in audit_rec if a == "zentao.finish"]
    assert rec[-1]["result"] == "deferred" and rec[-1]["before"] == "wait"


def test_finish_readback_failed(monkeypatch, audit_rec):
    fake = FakeFlowClient(["doing", "doing"])  # 读回仍 doing → 核验失败
    _use(monkeypatch, fake)
    rc = zt.cmd_finish(_finish_args())
    assert rc == 3
    rec = [d for _, a, d in audit_rec if a == "zentao.finish"]
    assert rec[-1]["result"] == "readback_mismatch"


def test_finish_config_manual_only_blocks(monkeypatch, audit_rec):
    fake = FakeFlowClient(["doing"])
    _use(monkeypatch, fake, mode="manual_only")
    rc = zt.cmd_finish(_finish_args())
    assert rc == 3
    assert fake.calls == []
    rec = [d for _, a, d in audit_rec if a == "zentao.finish"]
    assert rec[-1]["result"] == "blocked_by_config"


# ------------------------------------------------------------- close
def test_close_success_readback(monkeypatch, audit_rec):
    fake = FakeFlowClient(["done", "closed"])
    _use(monkeypatch, fake)
    rc = zt.cmd_close(_close_args())
    assert rc == 0
    assert fake.calls == [("close", "3413", "交付完成，关闭")]
    rec = [d for _, a, d in audit_rec if a == "zentao.close"]
    assert rec[-1]["result"] == "success"
    assert rec[-1]["before"] == "done" and rec[-1]["after"] == "closed"


def test_close_idempotent_when_closed(monkeypatch, audit_rec):
    fake = FakeFlowClient(["closed"])
    _use(monkeypatch, fake)
    rc = zt.cmd_close(_close_args())
    assert rc == 0
    assert fake.calls == []
    rec = [d for _, a, d in audit_rec if a == "zentao.close"]
    assert rec[-1]["result"] == "skipped_already_closed"


def test_close_deferred_when_not_done(monkeypatch, audit_rec):
    fake = FakeFlowClient(["doing"])
    _use(monkeypatch, fake)
    rc = zt.cmd_close(_close_args())
    assert rc == 3
    assert fake.calls == []  # 暂缓，不执行
    rec = [d for _, a, d in audit_rec if a == "zentao.close"]
    assert rec[-1]["result"] == "deferred" and "done" in rec[-1]["reason"]


def test_close_config_manual_only_blocks(monkeypatch, audit_rec):
    fake = FakeFlowClient(["done"])
    _use(monkeypatch, fake, mode="manual_only")
    rc = zt.cmd_close(_close_args())
    assert rc == 3
    assert fake.calls == []


def test_finish_and_close_are_separate_flows(monkeypatch, audit_rec):
    """finish 与 close 是两个独立状态流转：done 后仍需显式 close。"""
    fake = FakeFlowClient(["doing", "done", "done", "closed"])
    _use(monkeypatch, fake)
    assert zt.cmd_finish(_finish_args()) == 0
    assert zt.cmd_close(_close_args()) == 0
    assert [c[0] for c in fake.calls] == ["finish", "close"]
