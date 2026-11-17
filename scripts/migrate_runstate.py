# -*- coding: utf-8 -*-
"""历史 run-state.json → SQLite 迁移（幂等，可重复执行）。

把 execution/{project}/{task}/run-state.json 里的 DAG 节点状态迁入 node_dispatches：
  - 每个原 node.status=done 的节点 → 建一条 DONE attempt（attempt_id=att-<node>-migrated）
  - 原 running/dispatching 但无执行凭证（无 agent_id、无真实派发记录）→ UNVERIFIED
    （不假定成功/失败，禁止自动 DONE 或重复派发）
  - 原 failed/blocked/pending → 对应 NodeState

迁移前自动备份原 run-state.json 为 run-state.json.bak-<ts>。
幂等：已迁移的节点（attempt_id 含 -migrated）不重复插入。

用法：
    python -I scripts/migrate_runstate.py --project jeebootx --task-id 3415
    python -I scripts/migrate_runstate.py --all   # 迁移 execution/ 下所有任务
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for p in (_HERE, os.path.join(_REPO, "agent-manager")):
    if p not in sys.path:
        sys.path.insert(0, p)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from _config import load_config, exec_root  # noqa: E402
from state_manager import StateManager  # noqa: E402
from models import NodeDispatch, NodeState, ExecutionBackend, ExecutionRun, TaskLevel, TaskState  # noqa: E402
from exceptions import DuplicateExecutionError  # noqa: E402

DEFAULT_DB = os.path.join(_REPO, "agent-manager", "logs", "agent_manager.db")

# 旧 run-state.json node.status → NodeState
_LEGACY_MAP = {
    "done": NodeState.DONE,
    "running": NodeState.UNVERIFIED,      # 无凭证的 running → UNVERIFIED（不假定）
    "dispatching": NodeState.UNVERIFIED,
    "pending": NodeState.PENDING,
    "failed": NodeState.FAILED,
    "blocked": NodeState.BLOCKED,
    "unverified": NodeState.UNVERIFIED,
    "retry_pending": NodeState.RETRY_PENDING,
}

MIGRATED_TAG = "migrated"


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _is_migrated(disp: dict | None) -> bool:
    return bool(disp and MIGRATED_TAG in str(disp.get("attempt_id", "")))


def migrate_one(project_key: str, task_id: str, db: str = DEFAULT_DB, *, dry_run: bool = False) -> dict:
    """迁移单个任务的 run-state.json → SQLite。返回 {migrated, skipped, unverified, backup}。"""
    cfg = load_config(project_key, strict=False)
    exec_dir = exec_root(cfg, project_key, task_id)
    rs_path = os.path.join(exec_dir, "run-state.json")
    if not os.path.exists(rs_path):
        return {"migrated": 0, "skipped": 0, "unverified": 0, "backup": None, "note": "无 run-state.json"}
    with open(rs_path, encoding="utf-8") as f:
        rs = json.load(f)
    nodes = (rs.get("dag", {}) or {}).get("nodes", [])
    if not nodes:
        return {"migrated": 0, "skipped": 0, "unverified": 0, "backup": None, "note": "dag.nodes 为空"}

    state = StateManager(db)
    migrated = skipped = unverified = 0
    backup_path = None
    try:
        # execution_run：取或建
        rec = state.get_execution(project_key, task_id)
        if rec:
            eid = int(rec["id"])
        else:
            eid = state.create_execution(ExecutionRun(
                project_key=project_key, task_id=task_id,
                task_level=TaskLevel.M, workflow_status=TaskState.PENDING,
                current_stage=rs.get("stage", "migrated"), started_at=rs.get("updated_at") or _now(),
            ))
            state.log_event(eid, "migrate_execution_created", {"from": "run-state.json"})

        # 备份原文件（仅首次迁移；已有 .bak 则不重复备份）
        bak = rs_path + ".bak"
        if not os.path.exists(bak):
            import shutil
            backup_path = bak
            if not dry_run:
                shutil.copy2(rs_path, bak)

        for n in nodes:
            nid = n.get("id")
            if not nid:
                continue
            legacy = str(n.get("status", "pending")).lower()
            target = _LEGACY_MAP.get(legacy, NodeState.PENDING)
            attempt_id = "att-%s-%s" % (nid.lower(), MIGRATED_TAG)
            existing = state.get_node_dispatch(eid, nid, attempt_id)
            if existing:
                skipped += 1
                continue
            # main 节点（人工确认等）默认 claude_tool backend；有 commit 的 done 节点也归 claude_tool
            backend = ExecutionBackend.CLAUDE_TOOL
            nd = NodeDispatch(
                execution_id=eid, node_id=nid, attempt_id=attempt_id,
                agent_name=n.get("agent", "main"), execution_backend=backend,
                status=NodeState.PENDING,  # 先 PENDING 再合法转换
                agent_id=n.get("agent_id"),
                pid=n.get("pid"),
                dispatch_started_at=n.get("dispatch_started_at") or n.get("started_at"),
                started_at=n.get("started_at"),
                finished_at=n.get("finished_at"),
                last_seen_at=n.get("last_seen_at"),
                error_code=n.get("error_code") or (None if target != NodeState.FAILED else "LEGACY_FAILED"),
                error_message=n.get("error") or n.get("verification_note"),
            )
            if dry_run:
                migrated += 1
                if target == NodeState.UNVERIFIED:
                    unverified += 1
                continue
            # 事务：register（PENDING→DISPATCHING）→ 合法推进到 target
            try:
                state.register_node_dispatch(nd)
            except DuplicateExecutionError:
                skipped += 1
                continue
            # 合法转换链：PENDING→DISPATCHING（register 已写），再 DISPATCHING→target
            # 对 DONE：DISPATCHING→RUNNING→DONE（经 RUNNING 中转，保持状态机合法）
            if target == NodeState.DONE:
                state.update_node_dispatch(eid, nid, attempt_id, status=NodeState.RUNNING,
                                           started_at=nd.started_at or _now())
                state.update_node_dispatch(eid, nid, attempt_id, status=NodeState.DONE,
                                           finished_at=nd.finished_at or _now())
            elif target == NodeState.UNVERIFIED:
                state.update_node_dispatch(eid, nid, attempt_id, status=NodeState.UNVERIFIED,
                                           error_code=nd.error_code or "LEGACY_NO_PROOF",
                                           error_message=nd.error_message or "历史 running 无执行凭证，迁移为 UNVERIFIED")
            elif target == NodeState.FAILED:
                state.update_node_dispatch(eid, nid, attempt_id, status=NodeState.RUNNING)
                state.record_node_result(eid, nid, attempt_id, status=NodeState.FAILED,
                                         error_code=nd.error_code or "LEGACY_FAILED",
                                         error_message=nd.error_message)
            elif target == NodeState.BLOCKED:
                state.update_node_dispatch(eid, nid, attempt_id, status=NodeState.RUNNING)
                state.record_node_result(eid, nid, attempt_id, status=NodeState.BLOCKED,
                                         error_message=nd.error_message)
            else:  # PENDING / RETRY_PENDING：保持 DISPATCHING 不推进？不——PENDING 表示从未派发
                # 合法做法：回退为 PENDING 不可能（PENDING→DISPATCHING 单向）。
                # 对历史 pending 节点：标 UNVERIFIED 占位，由 plan 重新派发新 attempt。
                state.update_node_dispatch(eid, nid, attempt_id, status=NodeState.UNVERIFIED,
                                           error_code="LEGACY_PENDING",
                                           error_message="历史 pending，迁移占位，由 plan 重新派发新 attempt")
            migrated += 1
            if target == NodeState.UNVERIFIED:
                unverified += 1
            state.log_event(eid, "migrate_node", {"node": nid, "legacy": legacy, "target": target.value})
        return {"migrated": migrated, "skipped": skipped, "unverified": unverified,
                "backup": backup_path, "execution_id": eid}
    finally:
        state.close()


def _discover_all(execution_root: str) -> list[tuple[str, str]]:
    """扫描 execution/{project}/{task}/run-state.json。"""
    out = []
    if not os.path.isdir(execution_root):
        return out
    for proj in sorted(os.listdir(execution_root)):
        pd = os.path.join(execution_root, proj)
        if not os.path.isdir(pd):
            continue
        for task in sorted(os.listdir(pd)):
            if os.path.exists(os.path.join(pd, task, "run-state.json")):
                out.append((proj, task))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="migrate_runstate.py")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--project", default="")
    p.add_argument("--task-id", default="")
    p.add_argument("--all", action="store_true", help="迁移 execution/ 下所有任务")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    targets = []
    if args.all:
        cfg = load_config(strict=False)
        er = cfg.get("execution_root", os.path.join(_REPO, "execution"))
        targets = _discover_all(er)
    elif args.project and args.task_id:
        targets = [(args.project, str(args.task_id))]
    else:
        p.error("需要 --project + --task-id，或 --all")
    overall = {"tasks": 0, "migrated": 0, "skipped": 0, "unverified": 0}
    for proj, task in targets:
        r = migrate_one(proj, task, args.db, dry_run=args.dry_run)
        overall["tasks"] += 1
        overall["migrated"] += r.get("migrated", 0)
        overall["skipped"] += r.get("skipped", 0)
        overall["unverified"] += r.get("unverified", 0)
        print(json.dumps({"project": proj, "task": task, **r}, ensure_ascii=False))
    print(json.dumps({"overall": overall, "dry_run": args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
