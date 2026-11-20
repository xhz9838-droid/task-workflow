# -*- coding: utf-8 -*-
"""dispatch.py 状态语义回归测试（P0）：
    - WAITING_HUMAN 节点不得进入 executable（任务等待人工时）
    - 人工决策完成后可恢复派发
    - UNVERIFIED 不得自动重派
    - FAILED 超出重试预算后阻塞
    - gate 统一终止门禁
    - record-result 自动刷新 run-state 快照
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AM_DIR = os.path.join(REPO_ROOT, "agent-manager")
for _p in (AM_DIR, os.path.join(REPO_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from state_manager import StateManager  # noqa: E402
from models import (  # noqa: E402
    ExecutionBackend, ExecutionRun, NodeDispatch, NodeState, TaskLevel, TaskState,
)

DISPATCH = os.path.join(REPO_ROOT, "scripts", "dispatch.py")


def _home(tmp_path, agents=("a",)):
    root = tmp_path / "wf"
    (root / "config" / "projects").mkdir(parents=True)
    (root / "config" / "workflow.yaml").write_text(
        "execution_root: \"${WORKFLOW_HOME}/execution\"\nretry:\n  max_attempts: 2\n",
        encoding="utf-8")
    (root / "config" / "projects" / "demo.yaml").write_text(
        "project:\n  key: demo\n  agents:\n%s\n"
        % "".join("    %s: true\n" % a for a in agents), encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "_config.py").write_text("# marker\n", encoding="utf-8")
    return str(root)


def _tasks(home, project="demo", task="T1", nodes=None):
    d = os.path.join(home, "execution", project, task)
    os.makedirs(d, exist_ok=True)
    nodes = nodes or [{"id": "A", "agent": "a", "depends_on": []},
                      {"id": "B", "agent": "a", "depends_on": ["A"]}]
    with open(os.path.join(d, "tasks.yaml"), "w", encoding="utf-8") as f:
        import yaml
        yaml.safe_dump({"nodes": nodes}, f)
    return d


def _db(tmp_path):
    return str(tmp_path / "state.db")


def _execution(db, status=TaskState.RUNNING):
    sm = StateManager(db)
    eid = sm.create_execution(ExecutionRun(
        project_key="demo", task_id="T1", task_level=TaskLevel.M,
        workflow_status=status, current_stage="test"))
    sm.close()
    return eid


def _dispatch_node(db, eid, node, status):
    """造一个最新 attempt，状态为 status（需经合法转移）。"""
    sm = StateManager(db)
    try:
        attempt = "att-%s-%s" % (node.lower(), status.lower())
        sm.register_node_dispatch(NodeDispatch(
            execution_id=eid, node_id=node, attempt_id=attempt,
            agent_name="a", execution_backend=ExecutionBackend.CLAUDE_TOOL))
        if status == NodeState.FAILED:
            sm.record_node_result(eid, node, attempt, status=NodeState.FAILED)
        else:
            sm.confirm_node_running(eid, node, attempt, agent_id="agent-" + node)
            sm.update_node_dispatch(eid, node, attempt, status=status)
    finally:
        sm.close()


def _run(home, db, *args):
    env = dict(os.environ)
    env["WORKFLOW_HOME"] = home
    p = subprocess.run([sys.executable, "-I", DISPATCH, "--db", db, "--project", "demo",
                        "--task-id", "T1", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=REPO_ROOT, env=env, timeout=60)
    return p.returncode, p.stdout, p.stderr


def _plan(home, db):
    rc, out, err = _run(home, db, "plan")
    assert rc == 0, err
    return json.loads(out)


def test_waiting_human_not_executable_while_task_waits(tmp_path):
    home = _home(tmp_path)
    _tasks(home)
    db = _db(tmp_path)
    eid = _execution(db, TaskState.WAITING_HUMAN)
    _dispatch_node(db, eid, "A", NodeState.WAITING_HUMAN)

    plan = _plan(home, db)

    assert "A" not in [n["node"] for n in plan["executable"]]
    assert any(b["node"] == "A" and "等待人工" in b["reason"] for b in plan["blocked"])
    # 依赖 A 的 B 不应被执行
    assert "B" not in [n["node"] for n in plan["executable"]]


def test_waiting_human_resumes_after_decision(tmp_path):
    home = _home(tmp_path)
    _tasks(home)
    db = _db(tmp_path)
    eid = _execution(db, TaskState.RUNNING)  # 决策完成 → 任务恢复 RUNNING
    _dispatch_node(db, eid, "A", NodeState.WAITING_HUMAN)

    plan = _plan(home, db)

    assert "A" in [n["node"] for n in plan["executable"]]
    assert "B" not in [n["node"] for n in plan["executable"]]  # A 尚未 DONE


def test_unverified_never_auto_dispatched(tmp_path):
    home = _home(tmp_path)
    _tasks(home, nodes=[{"id": "A", "agent": "a", "depends_on": []}])
    db = _db(tmp_path)
    eid = _execution(db)
    _dispatch_node(db, eid, "A", NodeState.UNVERIFIED)

    plan = _plan(home, db)

    assert plan["executable"] == []
    assert any(b["node"] == "A" and "UNVERIFIED" in b["reason"] for b in plan["blocked"])


def test_failed_respects_retry_budget(tmp_path):
    home = _home(tmp_path)
    _tasks(home, nodes=[{"id": "A", "agent": "a", "depends_on": []}])
    db = _db(tmp_path)
    eid = _execution(db)
    # max_attempts=2 → 最多 3 次派发；先造 1 次失败 → 可重派
    _dispatch_node(db, eid, "A", NodeState.FAILED)
    assert "A" in [n["node"] for n in _plan(home, db)["executable"]]

    # 再造两次失败（共 3 次派发）→ 预算耗尽，阻塞
    sm = StateManager(db)
    for i in (2, 3):
        attempt = "att-a-f%d" % i
        sm.register_node_dispatch(NodeDispatch(
            execution_id=eid, node_id="A", attempt_id=attempt,
            agent_name="a", execution_backend=ExecutionBackend.CLAUDE_TOOL))
        sm.confirm_node_running(eid, "A", attempt, agent_id="x")
        sm.update_node_dispatch(eid, "A", attempt, status=NodeState.FAILED)
    sm.close()

    plan = _plan(home, db)
    assert plan["executable"] == []
    assert any("重试次数耗尽" in b["reason"] for b in plan["blocked"])


def test_gate_blocks_incomplete_and_pending_writes(tmp_path):
    home = _home(tmp_path)
    _tasks(home, nodes=[{"id": "A", "agent": "a", "depends_on": []}])
    db = _db(tmp_path)
    eid = _execution(db)

    rc, out, _ = _run(home, db, "gate")
    assert rc == 1
    body = json.loads(out)
    assert body["ok"] is False
    assert any(r["code"] == "NODE_INCOMPLETE" for r in body["reasons"])

    _dispatch_node(db, eid, "A", NodeState.DONE)
    sm = StateManager(db)
    sm.enqueue_pending_write("demo", "T1", "progress", {"text": "x"})
    sm.close()
    rc, out, _ = _run(home, db, "gate")
    body = json.loads(out)
    assert rc == 1
    assert any(r["code"] == "PENDING_WRITES" for r in body["reasons"])


def test_gate_passes_when_all_done(tmp_path):
    home = _home(tmp_path)
    _tasks(home, nodes=[{"id": "A", "agent": "a", "depends_on": []}])
    db = _db(tmp_path)
    eid = _execution(db)
    _dispatch_node(db, eid, "A", NodeState.DONE)

    rc, out, _ = _run(home, db, "gate")
    assert rc == 0, out
    assert json.loads(out)["ok"] is True


def test_gate_finalize_marks_completed(tmp_path):
    home = _home(tmp_path)
    _tasks(home, nodes=[{"id": "A", "agent": "a", "depends_on": []}])
    db = _db(tmp_path)
    eid = _execution(db)
    _dispatch_node(db, eid, "A", NodeState.DONE)

    rc, out, _ = _run(home, db, "gate", "--finalize")
    assert rc == 0, out
    assert json.loads(out)["finalized"] == "COMPLETED"
    sm = StateManager(db)
    try:
        got = [e for e in sm.list_executions() if e["id"] == eid][0]
    finally:
        sm.close()
    assert got["workflow_status"] == "COMPLETED"


def test_record_result_refreshes_run_state_snapshot(tmp_path):
    home = _home(tmp_path)
    exec_dir = _tasks(home, nodes=[{"id": "A", "agent": "a", "depends_on": []}])
    db = _db(tmp_path)
    eid = _execution(db)

    sm = StateManager(db)
    sm.register_node_dispatch(NodeDispatch(
        execution_id=eid, node_id="A", attempt_id="att-a-1",
        agent_name="a", execution_backend=ExecutionBackend.CLAUDE_TOOL))
    sm.confirm_node_running(eid, "A", "att-a-1", agent_id="x")
    sm.close()

    rc, out, err = _run(home, db, "record-result", "--node", "A",
                        "--attempt", "att-a-1", "--status", "DONE")
    assert rc == 0, err
    body = json.loads(out)
    assert body["recorded"] is True
    rs = os.path.join(exec_dir, "run-state.json")
    assert os.path.normcase(body["run_state"]) == os.path.normcase(rs)
    snap = json.loads(open(rs, encoding="utf-8").read())
    assert snap["dag"]["nodes"][0]["status"] == "done"
    assert snap["state_source"] == "sqlite"
