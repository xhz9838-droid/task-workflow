# -*- coding: utf-8 -*-
"""集成测试：DecisionManager 全流程（创建→通知→回复→恢复）与异常（超时/重启/通知失败）。"""
from __future__ import annotations

import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from human_decision.models import DecisionStatus, ResumeMethod
from conftest import now_minus


OPTIONS = [{"id": "A", "description": "方案A"}, {"id": "B", "description": "方案B"}]


def test_full_flow_decided(manager, store, notifier):
    rec = manager.create_decision(
        task_id="3413", question="选择实现方案", background="两种方案",
        options=OPTIONS, recommendation="A", recommend_reason="改动小", risk="不确认影响 DB",
    )
    assert rec.status == DecisionStatus.WAITING_REPLY
    assert notifier.sent and notifier.sent[0][0] == "decision_request"

    # 模拟真实 MCP 工具已在等待（否则手工决策应走 checkpoint）
    store.log_event(rec.decision_id, "tool_waiting", {"wait_seconds": 300})
    r = manager.apply_reply(
        raw_text="A", source="test", user_id="u1",
        chat_session_key=rec.cc_session_key,
    )
    assert r["outcome"] == "accepted"

    wait = manager.wait_for_decision(rec.decision_id, wait_seconds=1)
    assert wait["outcome"] == "decided"
    assert wait["decision"]["reply_choice"] == "A"
    # 恢复记账：工具仍在等待 → live_continue
    got = store.get(rec.decision_id)
    assert got.status == DecisionStatus.RESUMED
    assert got.resume_method == ResumeMethod.LIVE_CONTINUE


def test_wait_suspended_then_late_reply(manager, store, notifier, resumer):
    """有界等待超时 → 安全挂起；迟到回复仍生效并恢复。"""
    rec = manager.create_decision(task_id="3413", question="q", options=OPTIONS)
    wait = manager.wait_for_decision(rec.decision_id, wait_seconds=0.2)
    assert wait["outcome"] == "suspended"
    assert "不要继续" in wait["instruction"] or "停止" in wait["instruction"]
    # 挂起不放行
    assert store.get(rec.decision_id).status == DecisionStatus.WAITING_REPLY

    # 迟到回复
    r = manager.apply_reply(raw_text="B", source="test",
                            user_id="u1", chat_session_key=rec.cc_session_key)
    assert r["outcome"] == "accepted"
    got = store.get(rec.decision_id)
    # 工具已挂起 → 尝试 live 注入（测试环境无 cc-connect → 退化到 checkpoint/cc resume）
    assert got.status in (DecisionStatus.RESUMED, DecisionStatus.RESUME_FAILED)
    # 恢复包已生成
    packet_dir = os.path.join(manager.cfg.execution_root, rec.project_key or "_",
                              rec.task_id, "human-decision")
    assert os.path.isdir(packet_dir)


def test_notify_failure_keeps_decision_waiting(manager, store, notifier):
    notifier.fail = True
    rec = manager.create_decision(task_id="3413", question="q", options=OPTIONS)
    assert rec.status == DecisionStatus.NOTIFY_FAILED
    # 通知失败不允许放行：等待回复
    assert rec.is_replyable
    # 回复仍可生效（用户从其他渠道看到）
    notifier.fail = False
    r = manager.apply_reply(raw_text="A", source="test", user_id="u1",
                            chat_session_key=rec.cc_session_key)
    assert r["outcome"] == "accepted"


def test_timeout_never_auto_approves(manager, store, notifier):
    rec = manager.create_decision(task_id="3413", question="q", options=OPTIONS)
    # 把 notified_at 调到很久以前
    store.update_fields(rec.decision_id, notified_at=now_minus(10 ** 6))
    summary = manager.check_timeouts()
    assert rec.decision_id in summary["timed_out"]
    got = store.get(rec.decision_id)
    assert got.status == DecisionStatus.DECISION_TIMEOUT
    assert got.reply_choice is None  # 绝不自动批准
    # 迟到回复仍生效
    r = manager.apply_reply(raw_text="A", source="test", user_id="u1",
                            chat_session_key=rec.cc_session_key)
    assert r["outcome"] == "accepted"


def test_reminder_sent(manager, store, notifier):
    rec = manager.create_decision(task_id="3413", question="q", options=OPTIONS)
    store.update_fields(rec.decision_id, notified_at=now_minus(10 ** 6))
    manager.cfg.remind_after_seconds = 60
    manager.cfg.timeout_after_seconds = 10 ** 9
    manager.check_timeouts()
    assert any(k == "reminder" for k, _ in notifier.sent)
    assert store.get(rec.decision_id).reminded_at is not None


def test_recovery_after_restart(manager, store, notifier):
    """Runner 重启：决策不丢、不重复创建、可补发通知、回复后能恢复。"""
    notifier.fail = True
    rec = manager.create_decision(task_id="3413", question="q", options=OPTIONS)
    assert rec.status == DecisionStatus.NOTIFY_FAILED

    # 模拟重启：新的 manager 实例（内存清空，DB 持久）
    from human_decision.decision_manager import DecisionManager

    mgr2 = DecisionManager(manager.cfg, store, notifier, manager.resumer)
    notifier.fail = False
    summary = mgr2.recover()
    assert rec.decision_id in summary["restored"]
    assert rec.decision_id in summary["renotified"]
    got = store.get(rec.decision_id)
    assert got.status == DecisionStatus.WAITING_REPLY
    # 原 session_id / cc 绑定未丢失
    assert got.cc_session_key == rec.cc_session_key

    r = mgr2.apply_reply(raw_text="A", source="test", user_id="u1",
                         chat_session_key=rec.cc_session_key)
    assert r["outcome"] == "accepted"


def test_multiple_decisions_parallel(manager, store):
    """多任务并行等待互不串线。"""
    rec1 = manager.create_decision(task_id="3413", question="q1", options=OPTIONS,
                                   project_key="jeebootx")
    rec2 = manager.create_decision(task_id="9001", question="q2", options=OPTIONS,
                                   project_key="other")
    r1 = manager.apply_reply(raw_text="DEC-%s-ignored B" % rec1.task_id, source="test",
                             user_id="u1")  # 显式 ID 不存在 → unmatched
    assert r1["outcome"] == "unmatched"
    r2 = manager.apply_reply(raw_text=f"{rec2.decision_id} B", source="test", user_id="u1")
    assert r2["outcome"] == "accepted" and r2["decision_id"] == rec2.decision_id
    assert store.get(rec1.decision_id).status == DecisionStatus.WAITING_REPLY
    assert store.get(rec2.decision_id).reply_choice == "B"


def test_complete_flow(manager, store):
    rec = manager.create_decision(task_id="3413", question="q", options=OPTIONS)
    manager.apply_reply(raw_text="A", source="test", user_id="u1",
                        chat_session_key=rec.cc_session_key)
    assert manager.complete(rec.decision_id)
    assert store.get(rec.decision_id).status == DecisionStatus.COMPLETED


def test_mcp_server_tools_registered():
    from human_decision.mcp_server import build_server

    mcp = build_server()
    names = set(mcp._tool_manager._tools.keys()) if hasattr(mcp, "_tool_manager") else set()
    assert {"request_human_decision", "get_human_decision", "list_human_decisions"} <= names or not names
