# -*- coding: utf-8 -*-
"""工作日志工时计算与 Reporter 失败路径。"""
from __future__ import annotations

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
sys.path.insert(0, os.path.join(_ROOT, "agent-manager"))

import worklog  # noqa: E402
from zentao_reporter import ZenTaoReporter, ZenTaoWriteError  # noqa: E402


def _task(consumed=0, estimate=None, start=None, deadline=None, status="doing"):
    return {"id": "100", "status": status, "consumed": consumed,
            "estimate": estimate, "estStarted": start, "deadline": deadline}


def test_plan_baseline_8h_and_50_percent():
    entry = worklog.build_entry(_task(start="2026-11-23", deadline="2026-11-23"),
                                progress=50, work="完成设备围栏页面")
    assert entry["total"] == 8.0
    assert entry["consumed"] == 4.0
    assert entry["left"] == 4.0
    assert "完成设备围栏页面" in entry["work"]


def test_multi_stage_incremental_consumed():
    task = _task(start="2026-11-23", deadline="2026-11-23")
    expected = [(25, 2, 6), (50, 2, 4), (75, 2, 2), (100, 2, 0)]
    for pct, consumed, left in expected:
        e = worklog.build_entry(task, progress=pct, work="阶段 %s" % pct)
        assert (e["consumed"], e["left"]) == (consumed, left)
        task["consumed"] = e["cumulative"]


def test_small_task_only_final_log():
    e = worklog.build_entry(_task(estimate=8), progress=100, work="完成全部交付")
    assert e["consumed"] == 8.0 and e["left"] == 0.0


def test_same_stage_or_agent_retry_is_idempotent():
    task = _task(consumed=4, estimate=8)
    e = worklog.build_entry(task, progress=50, work="重复")
    assert e["skipped"] is True and e["consumed"] == 0.0
    # 不同 Agent 落在同一进度也不重复累计
    e2 = worklog.build_entry(task, progress=50, stage="qa", work="QA 重复")
    assert e2["skipped"] is True and e2["consumed"] == 0.0


def test_estimate_fallback_and_plan_priority():
    assert worklog.total_hours(_task(estimate=6)) == 6
    # 计划 2 个工作日（周一、周二）优先于 estimate
    assert worklog.total_hours(_task(estimate=3, start="2026-11-23",
                                     deadline="2026-11-24")) == 16


def test_weekend_not_counted_and_estimate_fallback():
    assert worklog.planned_workdays("2026-11-21", "2026-11-22") == 0
    assert worklog.total_hours(_task(estimate=5, start="2026-11-21",
                                     deadline="2026-11-22")) == 5


def test_no_baseline_is_rejected_without_inventing_hours():
    with pytest.raises(worklog.WorklogError) as ei:
        worklog.total_hours(_task())
    assert ei.value.code == "NO_BASELINE"


def test_empty_work_and_invalid_progress_rejected():
    with pytest.raises(worklog.WorklogError) as ei:
        worklog.build_entry(_task(estimate=8), progress=50, work="  ")
    assert ei.value.code == "EMPTY_WORK"
    with pytest.raises(worklog.WorklogError) as ei:
        worklog.build_entry(_task(estimate=8), progress=101, work="x")
    assert ei.value.code == "INVALID_PROGRESS"


def test_reporter_worklog_success_does_not_finish(monkeypatch):
    r = ZenTaoReporter()
    monkeypatch.setattr(r, "_run_zt", lambda args, timeout=120: json.dumps({
        "ok": True, "consumed": 4, "left": 4, "skipped": False,
    }))
    out = r.report_worklog(task_id="100", project_key="p", stage="dev",
                           progress=50, work="完成页面")
    assert out["ok"] is True and out["consumed"] == 4
    assert not hasattr(r, "finish_called")


def test_reporter_worklog_failure_is_not_success(monkeypatch):
    r = ZenTaoReporter()
    def _fail(args, timeout=120):
        raise RuntimeError("network down")
    monkeypatch.setattr(r, "_run_zt", _fail)
    with pytest.raises(ZenTaoWriteError):
        r.report_worklog(task_id="100", project_key="p", stage="dev",
                         progress=50, work="完成页面")


def test_zt_worklog_wrapper_success_and_failure(monkeypatch):
    import types
    try:
        import zt
    except (ImportError, SystemExit) as e:
        pytest.skip("禅道 Skill 未安装，跳过 zt 包装测试: %s" % e)

    task = _task(estimate=8)
    after = dict(task, consumed="4.00", left="4.00")
    class Client:
        def task_detail(self, tid):
            return after
    client = Client()
    monkeypatch.setattr(zt, "_client", lambda: client)
    monkeypatch.setattr(zt, "_load_own_task", lambda c, tid: task)
    monkeypatch.setattr(zt, "audit", lambda *a, **k: None)
    monkeypatch.setattr(zt.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=0, stdout="✅ 工时记录成功\n", stderr=""))

    args = types.SimpleNamespace(task="100", progress=50, work="完成页面",
                                stage="dev", total_hours=None, date="2026-11-23",
                                dry_run=False)
    assert zt.cmd_worklog(args) == 0

    monkeypatch.setattr(zt.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=1, stdout="", stderr="denied"))
    assert zt.cmd_worklog(args) == 3
