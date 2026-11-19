# -*- coding: utf-8 -*-
"""CLI 生命周期测试（Phase 0.5 §15.2）：五状态分离、Verifier 判定、重试、回写。

全部使用 Mock Runner/Verifier/Notifier/Reporter，不启动真实 Agent、不访问真实禅道。
覆盖场景：
- Agent exit code 0 但 Verifier 失败 → 任务不完成
- Agent exit code 非 0 / 超时 / 异常中断
- 自动重试成功、超过重试次数
- 外部 Provider 回写失败不影响 Agent/工作流结果
"""
from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AM_DIR = os.path.join(REPO_ROOT, "agent-manager")
if AM_DIR not in sys.path:
    sys.path.insert(0, AM_DIR)

import cli  # noqa: E402
import runner as runner_mod  # noqa: E402
import verifier as verifier_mod  # noqa: E402
from models import AgentState, TaskState, VerifyCheck, VerifyReport, VerifyStatus  # noqa: E402
from state_manager import StateManager  # noqa: E402


# --------------------------------------------------------------- 打桩
class FakeRun:
    pid = 4242


class FakeRunner:
    """按脚本返回 wait 结果；脚本项可为 (state, code) 或 Exception。"""

    script = []

    def __init__(self, state, logger=None):
        self._idx = len([r for r in FakeRunner._used])
        FakeRunner._used.append(self)

    def start(self, **kw):
        self.start_kwargs = kw
        return FakeRun()

    def wait(self, timeout_seconds=None):
        item = FakeRunner.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


FakeRunner._used = []


class FakeVerifier:
    report: VerifyReport = None

    def __init__(self, workdir=""):
        self.workdir = workdir

    def verify(self, **kw):
        return FakeVerifier.report


class FakeNotifier:
    def __init__(self, *a, **kw):
        self.calls = []

    def __getattr__(self, name):
        def _rec(**kw):
            self.calls.append((name, kw))
            return {"sent": True}
        return _rec


def make_report(git=VerifyStatus.PASS, commit="") -> VerifyReport:
    r = VerifyReport(git_status=git, commit=commit)
    r.checks = [VerifyCheck("git", git, "evidence")]
    r.compute_overall()
    return r


DECISION = SimpleNamespace(
    task_level=SimpleNamespace(value="M"),
    execution_budget_seconds=5,
    to_dict=lambda: {},
)


def run_with(tmp_path, monkeypatch, script, report=None, sleep=None):
    """运行 _execute_with_retry 一次，返回 (结果, state, notifier)。"""
    FakeRunner.script = list(script)
    FakeRunner._used = []
    FakeVerifier.report = report if report is not None else make_report()
    monkeypatch.setattr(runner_mod, "AgentRunner", FakeRunner)
    monkeypatch.setattr(verifier_mod, "Verifier", FakeVerifier)
    monkeypatch.setattr(time, "sleep", sleep or (lambda d: None))
    state = StateManager(str(tmp_path / "t.db"))
    notifier = FakeNotifier()
    args = SimpleNamespace(quiet=True, session_id="", dry_run=False)
    try:
        res = cli._execute_with_retry(
            args, {"retry": {"max_attempts": 2, "initial_delay_seconds": 0}},
            state, notifier, 1, "proj", "T1", DECISION, str(tmp_path), "prompt",
        )
        return res, state, notifier
    finally:
        pass  # state 由断言方关闭


# --------------------------------------------------------------- VerifyReport.passed
def test_verification_passed_rules():
    assert make_report(git=VerifyStatus.PASS).passed()[0] is True
    assert make_report(git=VerifyStatus.FAIL).passed()[0] is False
    assert make_report(git=VerifyStatus.NOT_RUN).passed()[0] is False
    r = make_report(git=VerifyStatus.PASS)
    r.blocked_summary = "test-x: BLOCKED"
    assert r.passed()[0] is False
    r2 = make_report(git=VerifyStatus.PASS)
    r2.tests = {"t1": VerifyStatus.FAIL}
    r2.compute_overall()
    assert r2.passed()[0] is False


# --------------------------------------------------------------- 五状态快照
def test_status_snapshot_five_dimensions():
    snap = cli._status_snapshot(AgentState.SUCCEEDED, 0, make_report(), 1,
                                "success", TaskState.COMPLETED.value)
    for key in ("agent_process_status", "agent_execution_status", "verification_status",
                "workflow_status", "external_provider_status"):
        assert key in snap
    assert snap["agent_process_status"] == "exit=0"
    # 仅 Git PASS、requirements 未提供 → compute_overall 为 PARTIAL（不虚报 SUCCESS）
    assert snap["verification_status"] == "PARTIAL"


# --------------------------------------------------------------- 执行/验收/重试
def test_success_first_attempt(tmp_path, monkeypatch):
    (state, code, report, attempt), st, nt = run_with(
        tmp_path, monkeypatch, [(AgentState.SUCCEEDED, 0)])
    assert state == AgentState.SUCCEEDED and attempt == 1
    assert report.passed()[0] is True
    st.close()


def test_exit0_but_verifier_failed(tmp_path, monkeypatch):
    """exit code 0 但 Verifier 失败 → 不算完成（任务书 15.2 场景 1）。"""
    rep = make_report(git=VerifyStatus.FAIL)
    (a_state, code, report, attempt), st, nt = run_with(
        tmp_path, monkeypatch, [(AgentState.SUCCEEDED, 0)], report=rep)
    ok, _ = report.passed()
    assert ok is False
    # PERMANENT（verify=FAILED 无可重试关键词）→ hand_to_main，不再启动第二次
    assert attempt == 1 and len(FakeRunner._used) == 1
    assert [n for n, _ in nt.calls if n == "qa_failed"]  # 验收失败已通知
    ev = [e for e in st.get_events(1) if e["event_type"] == "retry_decision"]
    assert ev and ev[-1]["details"]["action"] == "hand_to_main"
    st.close()


def test_nonzero_exit(tmp_path, monkeypatch):
    rep = make_report(git=VerifyStatus.FAIL)
    (a_state, code, report, attempt), st, nt = run_with(
        tmp_path, monkeypatch, [(AgentState.FAILED, 1)], report=rep)
    assert a_state == AgentState.FAILED and code == 1
    assert report.passed()[0] is False
    st.close()


def test_timeout_notified(tmp_path, monkeypatch):
    (a_state, code, report, attempt), st, nt = run_with(
        tmp_path, monkeypatch, [RuntimeError("执行超时 5s")])
    assert a_state == AgentState.TIMEOUT
    assert [n for n, _ in nt.calls if n == "agent_timeout"]
    st.close()


def test_crash_notified(tmp_path, monkeypatch):
    (a_state, code, report, attempt), st, nt = run_with(
        tmp_path, monkeypatch, [RuntimeError("pipe broken")])
    assert a_state == AgentState.FAILED
    assert [n for n, _ in nt.calls if n == "agent_crashed"]
    st.close()


def test_auto_retry_then_success(tmp_path, monkeypatch):
    """瞬时错误（connection reset）→ 自动重试 → 第二次成功（任务书 15.2 场景 5）。"""
    sleeps = []
    (a_state, code, report, attempt), st, nt = run_with(
        tmp_path, monkeypatch,
        [RuntimeError("connection reset by peer"), (AgentState.SUCCEEDED, 0)],
        sleep=sleeps.append)
    assert a_state == AgentState.SUCCEEDED and attempt == 2
    assert [n for n, _ in nt.calls if n == "auto_retry"]
    # 重试序号传入 AgentRunner（关联原执行记录）；重试决策已持久化
    assert [r.start_kwargs["attempt"] for r in FakeRunner._used] == [1, 2]
    ev = [e for e in st.get_events(1) if e["event_type"] == "retry_decision"]
    assert len(ev) == 1
    st.close()


def test_retry_exhausted(tmp_path, monkeypatch):
    """超过重试次数 → abort + 通知（任务书 15.2 场景 6）。"""
    (a_state, code, report, attempt), st, nt = run_with(
        tmp_path, monkeypatch,
        [RuntimeError("connection reset")] * 3)
    # max_attempts=2：decide 在 attempt > 2 时 abort → 共尝试 3 次后终止
    assert attempt == 3
    assert [n for n, _ in nt.calls if n == "final_failure"]
    st.close()


# --------------------------------------------------------------- 外部回写
def _finish_args(**over):
    kw = dict(zentao_finish=True, consumed=8.0, left=0.0, finished_date="2026-11-20",
              real_started="", dry_run=True, quiet=True)
    kw.update(over)
    return SimpleNamespace(**kw)


class FakeReporter:
    def __init__(self, *a, **kw):
        pass

    def finish(self, **kw):
        if kw.get("_fail"):
            raise RuntimeError("write failed")
        return {"ok": True}


def test_zentao_finish_skipped_when_fields_missing(tmp_path, monkeypatch):
    """工时/日期不推算：缺参 → 跳过回写，不影响返回（任务书 15.1）。"""
    nt = FakeNotifier()
    st = StateManager(str(tmp_path / "f.db"))
    s = cli._zentao_finish_with_notify(
        _finish_args(consumed=None, finished_date=""), st, nt, 1, "p", "T1")
    assert s == "skipped_missing_fields"
    st.close()


def test_zentao_finish_success_and_failure_isolated(tmp_path, monkeypatch):
    import zentao_reporter

    monkeypatch.setattr(zentao_reporter, "ZenTaoReporter", FakeReporter)
    nt = FakeNotifier()
    st = StateManager(str(tmp_path / "f.db"))
    s = cli._zentao_finish_with_notify(_finish_args(), st, nt, 1, "p", "T1")
    assert s == "success"

    # 回写失败 → failed_queued + 通知，不抛异常（不反向修改执行结果）
    class FailReporter(FakeReporter):
        def finish(self, **kw):
            raise RuntimeError("zentao down")

    monkeypatch.setattr(zentao_reporter, "ZenTaoReporter", FailReporter)
    s2 = cli._zentao_finish_with_notify(_finish_args(), st, nt, 1, "p", "T1")
    assert s2 == "failed_queued"
    assert [n for n, _ in nt.calls if n == "zentao_write_failed"]
    st.close()
