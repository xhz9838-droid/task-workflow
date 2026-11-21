# -*- coding: utf-8 -*-
"""多任务入口计划（dispatch.py batch-plan）：依赖波次、循环/未知依赖、只读状态。"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AM_DIR = os.path.join(REPO_ROOT, "agent-manager")
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
for _p in (AM_DIR, SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DISPATCH = os.path.join(SCRIPTS, "dispatch.py")


def make_home(tmp_path):
    root = tmp_path / "wf"
    (root / "config" / "projects").mkdir(parents=True)
    (root / "config" / "workflow.yaml").write_text(
        "execution_root: \"${WORKFLOW_HOME}/execution\"\n", encoding="utf-8")
    (root / "config" / "projects" / "demo.yaml").write_text(
        "project:\n  key: demo\n  agents:\n    a: true\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "_config.py").write_text("# marker\n", encoding="utf-8")
    return root


def write_dag(home, task, nodes=None, depends=None):
    d = home / "execution" / "demo" / str(task)
    d.mkdir(parents=True, exist_ok=True)
    nodes = nodes or [{"id": "A", "agent": "a", "depends_on": []}]
    lines = ["nodes:"]
    for n in nodes:
        lines.append("  - id: %s" % n["id"])
        lines.append("    agent: %s" % n.get("agent", "a"))
        lines.append("    depends_on: %s" % json.dumps(n.get("depends_on", [])))
    if depends:
        lines.append("depends_on_tasks: %s" % json.dumps(depends))
    (d / "tasks.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d


def run_batch(home, *args):
    env = dict(os.environ, WORKFLOW_HOME=str(home), PYTHONIOENCODING="utf-8")
    p = subprocess.run(
        [sys.executable, "-I", DISPATCH, "--project", "demo", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    return p.returncode, json.loads(p.stdout or "{}"), p.stderr


def test_independent_tasks_one_wave(tmp_path):
    home = make_home(tmp_path)
    write_dag(home, 101)
    write_dag(home, 102)
    rc, out, _ = run_batch(home, "--task-ids", "101,102", "batch-plan")
    assert rc == 0
    assert out["waves"] == [["101", "102"]]
    assert out["execution_order"] == ["101", "102"]   # 默认串行
    assert out["parallel_within_wave"] is False
    assert out["errors"] == []


def test_declared_dependency_creates_waves(tmp_path):
    home = make_home(tmp_path)
    write_dag(home, 101)
    write_dag(home, 102, depends=["101"])
    rc, out, _ = run_batch(home, "--task-ids", "101,102", "batch-plan")
    assert rc == 0
    assert out["waves"] == [["101"], ["102"]]


def test_cli_dependency_creates_waves(tmp_path):
    home = make_home(tmp_path)
    write_dag(home, 101)
    write_dag(home, 102)
    write_dag(home, 103)
    rc, out, _ = run_batch(home, "--task-ids", "101,102,103", "batch-plan",
                           "--depends", "103:101,102:101")
    assert rc == 0
    assert out["waves"] == [["101"], ["102", "103"]]


def test_cycle_detected(tmp_path):
    home = make_home(tmp_path)
    write_dag(home, 101, depends=["102"])
    write_dag(home, 102, depends=["101"])
    rc, out, _ = run_batch(home, "--task-ids", "101,102", "batch-plan")
    assert rc == 1
    assert any(e["code"] == "DEP_CYCLE" for e in out["errors"])


def test_unknown_dependency_detected(tmp_path):
    home = make_home(tmp_path)
    write_dag(home, 101)
    write_dag(home, 102, depends=["999"])
    rc, out, _ = run_batch(home, "--task-ids", "101,102", "batch-plan")
    assert rc == 1
    assert any(e["code"] == "DEP_UNKNOWN" for e in out["errors"])


def test_one_task_attention_does_not_block_others(tmp_path):
    home = make_home(tmp_path)
    write_dag(home, 101, nodes=[{"id": "A"}, {"id": "B", "depends_on": ["A"]}])
    write_dag(home, 102)
    # 让 101 的一个节点失败
    from state_manager import StateManager
    from models import (ExecutionRun, NodeDispatch, NodeState, TaskLevel, TaskState,
                        ExecutionBackend)
    db = str(tmp_path / "state.db")
    sm = StateManager(db)
    eid = sm.create_execution(ExecutionRun(
        project_key="demo", task_id="101", task_level=TaskLevel.M,
        workflow_status=TaskState.RUNNING, current_stage="test"))
    sm.register_node_dispatch(NodeDispatch(
        execution_id=eid, node_id="A", attempt_id="att-a",
        agent_name="a", execution_backend=ExecutionBackend.CLAUDE_TOOL))
    sm.record_node_result(eid, "A", "att-a", status=NodeState.FAILED)
    sm.close()
    rc, out, _ = run_batch(home, "--db", db, "--task-ids", "101,102", "batch-plan")
    assert rc == 0
    assert out["tasks"]["101"]["status"] == "attention"
    assert out["tasks"]["102"]["status"] == "not_started"
    assert out["waves"] == [["101", "102"]]     # 失败任务不阻塞独立任务


def test_done_task_reported_done(tmp_path):
    home = make_home(tmp_path)
    write_dag(home, 101)
    from state_manager import StateManager
    from models import (ExecutionRun, NodeDispatch, NodeState, TaskLevel, TaskState,
                        ExecutionBackend)
    db = str(tmp_path / "state.db")
    sm = StateManager(db)
    eid = sm.create_execution(ExecutionRun(
        project_key="demo", task_id="101", task_level=TaskLevel.M,
        workflow_status=TaskState.RUNNING, current_stage="test"))
    sm.register_node_dispatch(NodeDispatch(
        execution_id=eid, node_id="A", attempt_id="att-a",
        agent_name="a", execution_backend=ExecutionBackend.CLAUDE_TOOL))
    sm.update_node_dispatch(eid, "A", "att-a", status=NodeState.RUNNING)
    sm.record_node_result(eid, "A", "att-a", status=NodeState.DONE)
    sm.close()
    rc, out, _ = run_batch(home, "--db", db, "--task-ids", "101", "batch-plan")
    assert rc == 0
    assert out["tasks"]["101"]["status"] == "done"


def test_batch_plan_is_read_only(tmp_path):
    """batch-plan 不应对无 execution 的任务建空壳。"""
    home = make_home(tmp_path)
    write_dag(home, 101)
    db = str(tmp_path / "state.db")
    run_batch(home, "--db", db, "--task-ids", "101", "batch-plan")
    from state_manager import StateManager
    sm = StateManager(db)
    try:
        assert sm.get_execution("demo", "101") is None
    finally:
        sm.close()


def test_waiting_human_does_not_block_other_tasks(tmp_path):
    """一个任务 WAITING_HUMAN，其他任务仍可执行。"""
    home = make_home(tmp_path)
    write_dag(home, 101)
    write_dag(home, 102)
    from state_manager import StateManager
    from models import (ExecutionRun, NodeDispatch, NodeState, TaskLevel, TaskState,
                        ExecutionBackend)
    db = str(tmp_path / "state.db")
    sm = StateManager(db)
    eid = sm.create_execution(ExecutionRun(
        project_key="demo", task_id="101", task_level=TaskLevel.M,
        workflow_status=TaskState.RUNNING, current_stage="test"))
    sm.register_node_dispatch(NodeDispatch(
        execution_id=eid, node_id="A", attempt_id="att-a",
        agent_name="a", execution_backend=ExecutionBackend.CLAUDE_TOOL))
    sm.update_node_dispatch(eid, "A", "att-a", status=NodeState.RUNNING)
    sm.update_node_dispatch(eid, "A", "att-a", status=NodeState.WAITING_HUMAN)
    sm.close()
    rc, out, _ = run_batch(home, "--db", db, "--task-ids", "101,102", "batch-plan")
    assert rc == 0
    assert out["tasks"]["101"]["status"] == "waiting_human"
    assert out["tasks"]["102"]["status"] == "not_started"
    assert out["errors"] == []


def test_args_to_batch_pass_through(tmp_path):
    """_args 解析结果完整传给 batch-plan（Skill 入口 → 调度入口）。"""
    from _args import parse_invocation
    parsed = parse_invocation(["demo", "3442", "3443", "3444", "3445"])
    home = make_home(tmp_path)
    for t in parsed["task_ids"]:
        write_dag(home, t)
    rc, out, _ = run_batch(home, "--task-ids", ",".join(parsed["task_ids"]), "batch-plan")
    assert rc == 0
    assert out["task_ids"] == parsed["task_ids"]
