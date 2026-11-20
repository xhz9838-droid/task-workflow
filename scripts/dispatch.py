# -*- coding: utf-8 -*-
"""DAG 派发统一入口（编排层一致性保障）。

职责（不重叠 state_manager / runner / verifier 已有能力）：
    - plan             : 计算 DAG 可执行节点（依赖满足 + 未完成 + 未 L3 阻塞）
    - register-dispatch: 事务登记 DISPATCHING + attempt_id（Python 不调 Agent Tool）
    - confirm-running  : 主控取得真实 agent_id 后确认 RUNNING
    - record-result    : 记录 DONE/FAILED/BLOCKED（执行层结果，非验收层）
    - reconcile        : 对账 DISPATCHING 超时 / 僵尸 RUNNING / 迟到通知
    - export-state     : 从 SQLite 生成 run-state.json（只读快照）
    - status           : 查节点/Agent 执行状态

设计约束（硬性）：
    - SQLite（state_manager）是 DAG 节点状态唯一真相源。
    - run-state.json 只作为 export-state 导出的只读快照，主控/Skill/Subagent 禁止直接改。
    - 本脚本不调用 Claude Code Agent Tool，不启动 Claude CLI 子进程。
      主控必须：register-dispatch → 调真实 Agent 工具 → 拿 agent_id → confirm-running。
    - Agent Tool（CLAUDE_TOOL backend）只有 agent_id，无 pid、无进程探活。
      reconcile 对其 RUNNING 无法 pid 探活 → UNVERIFIED，不假定成功/失败。
    - 同一 (node, attempt) 唯一；不同 attempt 隔离；旧 attempt 迟到通知不覆盖新 attempt。

用法：
    python -I scripts/dispatch.py plan --project jeebootx --task-id 3415
    python -I scripts/dispatch.py register-dispatch --project jeebootx --task-id 3415 \\
        --node C1 --agent dw-qa-engineer --backend claude_tool
    python -I scripts/dispatch.py confirm-running --project jeebootx --task-id 3415 \\
        --node C1 --attempt att-c1-2 --agent-id <real_agent_id>
    python -I scripts/dispatch.py record-result --project jeebootx --task-id 3415 \\
        --node C1 --attempt att-c1-2 --status FAILED --error "StreamNoEventsError"
    python -I scripts/dispatch.py reconcile --project jeebootx --task-id 3415
    python -I scripts/dispatch.py export-state --project jeebootx --task-id 3415
    python -I scripts/dispatch.py status --project jeebootx --task-id 3415 [--node C1]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for p in (_HERE, os.path.join(_REPO, "agent-manager")):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from _home import resolve_workflow_home  # noqa: E402
from _config import load_config, exec_root  # noqa: E402
from audit import audit  # noqa: E402
from state_manager import StateManager  # noqa: E402
from models import NodeState, ExecutionBackend  # noqa: E402
from exceptions import DuplicateExecutionError  # noqa: E402

DEFAULT_DB = os.path.join(_REPO, "agent-manager", "logs", "agent_manager.db")
DISPATCHING_TIMEOUT_SECONDS = 600   # DISPATCHING 超 10min 无 confirm-running → 对账
RUNNING_STALE_SECONDS = 1800        # RUNNING 无 last_seen 更新超 30min → 对账（不杀，仅标记）


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _new_attempt_id(node_id: str) -> str:
    return "att-%s-%s" % (node_id.lower(), uuid.uuid4().hex[:8])


def _load_tasks_yaml(exec_dir: str) -> dict:
    """读 tasks.yaml（DAG 定义）。无则空 dict。"""
    import yaml  # type: ignore
    path = os.path.join(exec_dir, "tasks.yaml")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _node_status_from_dispatch(disp: dict | None) -> str:
    """把 NodeState 映射到 run-state.json 兼容的 node.status 字符串。"""
    if not disp:
        return "pending"
    m = {
        NodeState.PENDING.value: "pending",
        NodeState.DISPATCHING.value: "dispatching",
        NodeState.RUNNING.value: "running",
        NodeState.DONE.value: "done",
        NodeState.FAILED.value: "failed",
        NodeState.BLOCKED.value: "blocked",
        NodeState.RETRY_PENDING.value: "retry_pending",
        NodeState.UNVERIFIED.value: "unverified",
        NodeState.WAITING_HUMAN.value: "waiting_human",
    }
    return m.get(disp["status"], disp["status"])


# --------------------------------------------------------------- execution_id 解析
def _resolve_execution_id(state: StateManager, project_key: str, task_id: str) -> int:
    """取任务最近一次 execution_run；不存在则创建一条（PENDING）。

    历史任务可能无 execution_runs 记录（C1 故障前主控只写 run-state.json）。
    migrate_runstate.py 负责补建；此处兜底：缺则建空壳，不丢现有 node_dispatches。
    """
    rec = state.get_execution(project_key, task_id)
    if rec:
        return int(rec["id"])
    from models import ExecutionRun, TaskLevel, TaskState
    eid = state.create_execution(ExecutionRun(
        project_key=project_key, task_id=task_id,
        task_level=TaskLevel.M, workflow_status=TaskState.PENDING,
        current_stage="dispatch-bootstrap", started_at=_now(),
    ))
    state.log_event(eid, "execution_bootstrap", {"reason": "dispatch 兜底建 execution_run"})
    return eid


# --------------------------------------------------------------- plan
def cmd_plan(args) -> int:
    """计算 DAG 可执行节点：pending + 依赖全 done + agent 启用 + 未 L3 阻塞。

    状态源：tasks.yaml（DAG 结构）+ SQLite node_dispatches（节点当前态）。
    输出 JSON：{executable, in_progress, blocked, done}。

    硬性规则：
      - WAITING_HUMAN / UNVERIFIED / BLOCKED 节点**不得**自动重派，只进 blocked。
      - FAILED / RETRY_PENDING 在重试预算内可重派；超出上限进 blocked。
      - 依赖未满足的节点不出现（既不可执行也不阻塞其它节点）。
    """
    cfg = load_config(args.project, strict=False)
    exec_dir = exec_root(cfg, args.project, str(args.task_id))
    dag = _load_tasks_yaml(exec_dir)
    nodes = dag.get("nodes", [])
    enabled = set()
    for k, v in (cfg.get("project", {}).get("agents", {}) or {}).items():
        if v is True:
            enabled.add(k)
    # 重试预算：max_attempts 次重试 = 最多 max_attempts+1 次派发尝试
    retry_cfg = cfg.get("retry", {}) or {}
    max_attempts = int(retry_cfg.get("max_attempts", 2)) + 1
    state = StateManager(args.db)
    try:
        eid = _resolve_execution_id(state, args.project, str(args.task_id))
        all_disps = state.list_node_dispatches(eid)
        attempts_count: dict[str, int] = {}
        for d in all_disps:
            attempts_count[d["node_id"]] = attempts_count.get(d["node_id"], 0) + 1
        done_ids = set()
        for n in nodes:
            disp = state.latest_node_dispatch(eid, n["id"])
            if disp and disp["status"] == NodeState.DONE.value:
                done_ids.add(n["id"])
        executable, in_progress, blocked = [], [], []
        exec_rec = state.get_execution(args.project, str(args.task_id))
        exec_status = (exec_rec or {}).get("workflow_status") or ""
        for n in nodes:
            disp = state.latest_node_dispatch(eid, n["id"])
            nstat = _node_status_from_dispatch(disp)
            deps = n.get("depends_on", []) or []
            deps_done = all(d in done_ids for d in deps)
            agent_on = n.get("agent", "main") == "main" or n.get("agent") in enabled
            if nstat == "done":
                continue
            if nstat in ("dispatching", "running"):
                in_progress.append({"node": n["id"], "agent": n.get("agent"), "status": nstat,
                                    "attempt_id": disp["attempt_id"] if disp else None})
                continue
            if nstat == "waiting_human":
                # 任务仍处 WAITING_HUMAN → 阻塞；人工决策已完成（任务已恢复 RUNNING 等）
                # 则允许重派该节点，恢复原工作流。
                if exec_status == "WAITING_HUMAN":
                    blocked.append({"node": n["id"], "reason": "等待人工决策（WAITING_HUMAN）"})
                    continue
                if not deps_done:
                    continue
                if not agent_on:
                    blocked.append({"node": n["id"], "reason": "agent 未启用"})
                    continue
                executable.append({"node": n["id"], "agent": n.get("agent"), "name": n.get("name"),
                                   "attempts": attempts_count.get(n["id"], 0),
                                   "note": "人工决策已完成，恢复派发"})
                continue
            if nstat == "unverified":
                blocked.append({"node": n["id"], "reason": "执行凭证 UNVERIFIED，需人工确认后再派发"})
                continue
            if nstat == "blocked":
                blocked.append({"node": n["id"], "reason": "node BLOCKED"})
                continue
            if nstat in ("failed", "retry_pending"):
                if attempts_count.get(n["id"], 0) >= max_attempts:
                    blocked.append({"node": n["id"],
                                    "reason": "重试次数耗尽（%d/%d）" % (
                                        attempts_count.get(n["id"], 0), max_attempts)})
                    continue
                # 预算内可重派，继续走下面的依赖/Agent 检查
            if not deps_done:
                continue  # 依赖未满足，不计入可执行
            if not agent_on:
                blocked.append({"node": n["id"], "reason": "agent 未启用"})
                continue
            executable.append({"node": n["id"], "agent": n.get("agent"), "name": n.get("name"),
                               "attempts": attempts_count.get(n["id"], 0)})
        out = {"execution_id": eid, "executable": executable, "in_progress": in_progress,
               "blocked": blocked, "done": sorted(done_ids)}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    finally:
        state.close()


# --------------------------------------------------------------- register-dispatch
def cmd_register_dispatch(args) -> int:
    """事务登记 DISPATCHING + attempt_id。Python 不调 Agent Tool。

    幂等防护：同 (node, attempt) 已存在 → DuplicateExecutionError（exit=4 LOCKED）。
    若节点已有未终结 attempt 且未指定 --force-new-attempt → 报错提示先 record-result 再重派。
    """
    from models import NodeDispatch
    cfg = load_config(args.project, strict=False)
    state = StateManager(args.db)
    try:
        eid = _resolve_execution_id(state, args.project, str(args.task_id))
        # 防重复派发：节点已有 DISPATCHING/RUNNING 的最新 attempt → 拒绝
        latest = state.latest_node_dispatch(eid, args.node)
        if latest and latest["status"] in (NodeState.DISPATCHING.value, NodeState.RUNNING.value):
            sys.stderr.write(
                "[BLOCKED] 节点 %s 已有未终结 attempt %s（status=%s）。"
                " 先 record-result 再 register-dispatch 新 attempt。\n"
                % (args.node, latest["attempt_id"], latest["status"])
            )
            return 4
        # UNVERIFIED 必须人工确认；WAITING_HUMAN 在任务仍等待人工时禁止重派。
        if latest and latest["status"] == NodeState.UNVERIFIED.value and not args.force_new_attempt:
            sys.stderr.write(
                "[BLOCKED] 节点 %s 最新状态为 UNVERIFIED，需人工确认执行凭证后才能重派"
                "（确认后加 --force-new-attempt）。\n" % args.node
            )
            return 4
        if latest and latest["status"] == NodeState.WAITING_HUMAN.value and not args.force_new_attempt:
            exec_rec = state.get_execution(args.project, str(args.task_id)) or {}
            if (exec_rec.get("workflow_status") or "") == "WAITING_HUMAN":
                sys.stderr.write(
                    "[BLOCKED] 节点 %s 仍在等待人工决策（任务 WAITING_HUMAN）；"
                    "决策完成后再派发。\n" % args.node
                )
                return 4
        attempt_id = args.attempt_id or _new_attempt_id(args.node)
        backend = ExecutionBackend(args.backend)
        nd = NodeDispatch(
            execution_id=eid, node_id=args.node, attempt_id=attempt_id,
            agent_name=args.agent, execution_backend=backend,
        )
        try:
            nid = state.register_node_dispatch(nd)
        except DuplicateExecutionError as e:
            sys.stderr.write("[BLOCKED] %s\n" % e)
            return 4
        rec = state.get_node_dispatch(eid, args.node, attempt_id)
        audit(str(args.task_id), "dispatch_register", {
            "project_key": args.project, "node": args.node, "attempt_id": attempt_id,
            "agent": args.agent, "backend": args.backend, "dispatch_id": nid,
        }, project_key=args.project)
        print(json.dumps({"registered": True, "execution_id": eid, "node": args.node,
                          "attempt_id": attempt_id, "status": rec["status"],
                          "dispatch_started_at": rec["dispatch_started_at"],
                          "next": "主控调用真实 Agent 工具 → 拿 agent_id → confirm-running"},
                         ensure_ascii=False, indent=2))
        return 0
    finally:
        state.close()


# --------------------------------------------------------------- confirm-running
def cmd_confirm_running(args) -> int:
    """主控取得真实 agent_id（CLAUDE_TOOL）/ pid（CLI）后确认 RUNNING。"""
    cfg = load_config(args.project, strict=False)
    state = StateManager(args.db)
    try:
        eid = _resolve_execution_id(state, args.project, str(args.task_id))
        pid = int(args.pid) if args.pid else None
        rec = state.confirm_node_running(
            eid, args.node, args.attempt,
            agent_id=args.agent_id, pid=pid,
        )
        audit(str(args.task_id), "dispatch_confirm_running", {
            "project_key": args.project, "node": args.node, "attempt_id": args.attempt,
            "agent_id": args.agent_id, "pid": pid, "status": rec["status"],
        }, project_key=args.project)
        print(json.dumps({"confirmed": True, "node": args.node, "attempt_id": args.attempt,
                          "status": rec["status"], "started_at": rec["started_at"]},
                         ensure_ascii=False, indent=2))
        return 0
    finally:
        state.close()


# --------------------------------------------------------------- record-result
def cmd_record_result(args) -> int:
    """记录节点执行结果（DONE/FAILED/BLOCKED）。迟到通知判定在内。"""
    cfg = load_config(args.project, strict=False)
    state = StateManager(args.db)
    try:
        eid = _resolve_execution_id(state, args.project, str(args.task_id))
        # 迟到通知：该 attempt 非最新 → 记事件但不覆盖最新 attempt 状态
        if not state.is_latest_attempt(eid, args.node, args.attempt):
            state.log_event(eid, "late_notification", {
                "node_id": args.node, "attempt_id": args.attempt,
                "reported_status": args.status, "note": "迟到通知，不改最新 attempt",
            })
            audit(str(args.task_id), "dispatch_late_notification", {
                "project_key": args.project, "node": args.node, "attempt_id": args.attempt,
                "reported_status": args.status, "note": "迟到，已记事件未覆盖最新",
            }, project_key=args.project)
            print(json.dumps({"late_notification": True, "node": args.node,
                              "attempt_id": args.attempt, "note": "非最新 attempt，已记事件未覆盖"},
                             ensure_ascii=False, indent=2))
            return 0
        status = NodeState(args.status)
        rec = state.record_node_result(
            eid, args.node, args.attempt, status=status,
            error_code=args.error_code, error_message=args.error,
        )
        audit(str(args.task_id), "dispatch_record_result", {
            "project_key": args.project, "node": args.node, "attempt_id": args.attempt,
            "status": status.value, "error_code": args.error_code,
            "error": (args.error or "")[:200],
        }, project_key=args.project)
        # 自动刷新 run-state.json 只读快照（失败不影响已记录的执行结果）
        export_info = None
        try:
            export_info = _export_snapshot(args.project, str(args.task_id), args.db)
        except Exception as e:
            sys.stderr.write("[WARN] run-state 快照刷新失败：%s\n" % e)
        payload = {"recorded": True, "node": args.node, "attempt_id": args.attempt,
                   "status": rec["status"], "finished_at": rec["finished_at"]}
        if export_info:
            payload["run_state"] = export_info["path"]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        state.close()


# --------------------------------------------------------------- reconcile
def cmd_reconcile(args) -> int:
    """对账：DISPATCHING 超时 / 僵尸 RUNNING / Agent Tool 无法探活。

    规则：
      - DISPATCHING 超 DISPATCHING_TIMEOUT_SECONDS 仍无 confirm-running
        → 标 UNVERIFIED（待人工确认是否真派发），不自动重派。
      - CLI_SUBPROCESS RUNNING 且 pid 不存活 → FAILED（进程消失）。
      - CLAUDE_TOOL RUNNING 无 pid 探活能力
        → 若 last_seen_at 超 RUNNING_STALE_SECONDS 且无报告/通知 → UNVERIFIED（不假定成功/失败）。
      - 幂等：已 UNVERIFIED/FAILED 的不重复对账。
    """
    from monitor import pid_alive
    cfg = load_config(args.project, strict=False)
    state = StateManager(args.db)
    try:
        eid = _resolve_execution_id(state, args.project, str(args.task_id))
        open_disps = state.list_open_node_dispatches(eid)
        now = datetime.datetime.now().astimezone()
        actions = []
        for d in open_disps:
            st = d["status"]
            try:
                ds_at = datetime.datetime.fromisoformat(d["dispatch_started_at"]) if d["dispatch_started_at"] else None
                ls_at = datetime.datetime.fromisoformat(d["last_seen_at"]) if d["last_seen_at"] else None
            except Exception:
                ds_at = ls_at = None
            if st == NodeState.DISPATCHING.value and ds_at:
                age = (now - ds_at).total_seconds()
                if age > DISPATCHING_TIMEOUT_SECONDS:
                    state.update_node_dispatch(eid, d["node_id"], d["attempt_id"],
                                               status=NodeState.UNVERIFIED,
                                               error_code="DISPATCHING_TIMEOUT",
                                               error_message="DISPATCHING %ds 无 confirm-running，待人工对账" % int(age))
                    actions.append({"node": d["node_id"], "attempt": d["attempt_id"],
                                    "action": "DISPATCHING→UNVERIFIED", "age_seconds": int(age)})
            elif st == NodeState.RUNNING.value:
                backend = d["execution_backend"]
                if backend == ExecutionBackend.CLI_SUBPROCESS.value and d.get("pid"):
                    if not pid_alive(int(d["pid"])):
                        state.record_node_result(
                            eid, d["node_id"], d["attempt_id"], status=NodeState.FAILED,
                            error_code="PROCESS_DEAD", error_message="CLI 进程 pid=%s 已消失" % d["pid"])
                        actions.append({"node": d["node_id"], "attempt": d["attempt_id"],
                                        "action": "RUNNING→FAILED(process_dead)", "pid": d["pid"]})
                elif backend == ExecutionBackend.CLAUDE_TOOL.value:
                    # 无 pid 探活：仅当长时间无 last_seen 且无报告 → UNVERIFIED（不假定）
                    if ls_at:
                        stale = (now - ls_at).total_seconds()
                        if stale > RUNNING_STALE_SECONDS:
                            state.update_node_dispatch(
                                eid, d["node_id"], d["attempt_id"], status=NodeState.UNVERIFIED,
                                error_code="RUNNING_STALE_NO_SIGNAL",
                                error_message="CLAUDE_TOOL RUNNING %ds 无 last_seen/通知，无法探活→UNVERIFIED" % int(stale))
                            actions.append({"node": d["node_id"], "attempt": d["attempt_id"],
                                            "action": "RUNNING→UNVERIFIED(stale_no_signal)", "stale_seconds": int(stale)})
        audit(str(args.task_id), "dispatch_reconcile", {
            "project_key": args.project, "actions": actions, "open_before": len(open_disps),
        }, project_key=args.project)
        print(json.dumps({"reconciled": True, "actions": actions,
                          "open_nodes_before": len(open_disps)}, ensure_ascii=False, indent=2))
        return 0
    finally:
        state.close()


# --------------------------------------------------------------- export-state
def _write_snapshot(state: StateManager, eid: int, project_key: str, task_id: str) -> dict:
    """从 SQLite 重建 run-state.json 快照并原子写入（不打印、不审计）。"""
    cfg = load_config(project_key, strict=False)
    exec_dir = exec_root(cfg, project_key, str(task_id))
    exec_rec = state.get_execution(project_key, str(task_id))
    disps = state.list_node_dispatches(eid)
    events = state.get_events(eid)
    # 读现有 run-state.json 作底（保留 tasks.yaml 引用、blockers、checkpoints 历史等
    # 非 DAG 节点态字段——这些不是执行凭证，迁移期兼容）
    rs_path = os.path.join(exec_dir, "run-state.json")
    base = {}
    if os.path.exists(rs_path):
        try:
            with open(rs_path, encoding="utf-8") as f:
                base = json.load(f)
        except Exception:
            base = {}
    dag = _load_tasks_yaml(exec_dir)
    nodes_def = {n["id"]: n for n in dag.get("nodes", [])}
    by_node: dict[str, list[dict]] = {}
    for d in disps:
        by_node.setdefault(d["node_id"], []).append(d)
    out_nodes = []
    for nid, ndef in nodes_def.items():
        attempts = sorted(by_node.get(nid, []), key=lambda x: x["id"])
        latest = attempts[-1] if attempts else None
        node = {
            "id": nid, "agent": ndef.get("agent"),
            "status": _node_status_from_dispatch(latest),
            "depends_on": ndef.get("depends_on", []) or [],
            "name": ndef.get("name"),
            "note": ndef.get("note"),
        }
        if latest:
            node["attempt_id"] = latest["attempt_id"]
            node["agent_id"] = latest.get("agent_id")
            node["pid"] = latest.get("pid")
            node["execution_backend"] = latest.get("execution_backend")
            node["dispatch_started_at"] = latest.get("dispatch_started_at")
            node["started_at"] = latest.get("started_at")
            node["finished_at"] = latest.get("finished_at")
            node["last_seen_at"] = latest.get("last_seen_at")
            node["error"] = latest.get("error_message")
            node["attempts"] = len(attempts)
        else:
            node["attempts"] = 0
        out_nodes.append(node)
    snapshot = base
    snapshot["schema_version"] = snapshot.get("schema_version", 2)
    snapshot["project_key"] = project_key
    snapshot["task_id"] = str(task_id)
    snapshot["stage"] = exec_rec.get("current_stage") if exec_rec else snapshot.get("stage")
    snapshot["updated_at"] = _now()
    snapshot["state_source"] = "sqlite"  # 标记唯一真相源
    snapshot["execution_id"] = eid
    snapshot["dag"] = {"file": "tasks.yaml", "nodes": out_nodes}
    snapshot["execution_events_count"] = len(events)
    tmp = rs_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)
    os.replace(tmp, rs_path)
    return {"path": rs_path, "nodes": len(out_nodes), "execution_id": eid,
            "events": len(events)}


def _export_snapshot(project_key: str, task_id: str, db: str) -> dict:
    """独立导出快照（供 record-result 自动刷新与 export-state 共用）。"""
    state = StateManager(db)
    try:
        eid = _resolve_execution_id(state, project_key, str(task_id))
        info = _write_snapshot(state, eid, project_key, str(task_id))
    finally:
        state.close()
    audit(str(task_id), "dispatch_export_state", {
        "project_key": project_key, "nodes": info["nodes"],
        "events": info["events"], "path": info["path"],
    }, project_key=project_key)
    return info


def cmd_export_state(args) -> int:
    """从 SQLite 生成 run-state.json（只读快照）。原子写，失败不损原文件。

    SQLite 提交成功但 JSON 导出失败时以 SQLite 为准——重跑本命令即可重建。
    """
    info = _export_snapshot(args.project, args.task_id, args.db)
    print(json.dumps({"exported": True, "path": info["path"], "nodes": info["nodes"],
                      "execution_id": info["execution_id"]}, ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------- flush-writes
def cmd_flush_writes(args) -> int:
    """重试 pending_writes 队列（禅道 progress/finish/close）。"""
    from zentao_reporter import ZenTaoReporter
    state = StateManager(args.db)
    try:
        reporter = ZenTaoReporter(state)
        res = reporter.flush_pending(str(args.task_id))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("failed", 0) == 0 else 1
    finally:
        state.close()


# --------------------------------------------------------------- gate
def cmd_gate(args) -> int:
    """统一终止门禁：全部节点 DONE 且无等待人工/未刷写回写/存活 Agent 时才允许结束。

    exit 0 = 可以结束；exit 1 = 不可结束（reasons 说明原因）。
    """
    cfg = load_config(args.project, strict=False)
    exec_dir = exec_root(cfg, args.project, str(args.task_id))
    dag = _load_tasks_yaml(exec_dir)
    nodes = dag.get("nodes", [])
    state = StateManager(args.db)
    try:
        eid = _resolve_execution_id(state, args.project, str(args.task_id))
        exec_rec = state.get_execution(args.project, str(args.task_id)) or {}
        reasons = []
        node_states = {}
        for n in nodes:
            disp = state.latest_node_dispatch(eid, n["id"])
            st = _node_status_from_dispatch(disp)
            node_states[n["id"]] = st
        if not nodes:
            reasons.append({"code": "NO_DAG", "detail": "tasks.yaml 无节点定义"})
        incomplete = {k: v for k, v in node_states.items() if v != "done"}
        if incomplete:
            reasons.append({"code": "NODE_INCOMPLETE", "detail": incomplete})
        waiting = sorted(k for k, v in node_states.items() if v == "waiting_human")
        if waiting:
            reasons.append({"code": "WAITING_HUMAN", "detail": waiting})
        if (exec_rec.get("workflow_status") or "") == "WAITING_HUMAN":
            reasons.append({"code": "TASK_WAITING_HUMAN",
                            "detail": "execution 处于 WAITING_HUMAN"})
        live = state.find_live_agent(eid)
        if live:
            reasons.append({"code": "LIVE_AGENT", "detail": {
                "agent_id": live.get("agent_id"), "status": live.get("status")}})
        pending = state.get_pending_writes(str(args.task_id))
        if pending:
            reasons.append({"code": "PENDING_WRITES",
                            "detail": len(pending)})
        out = {"ok": not reasons, "execution_id": eid,
               "nodes": node_states, "pending_writes": len(pending),
               "reasons": reasons}
        if not reasons and getattr(args, "finalize", False):
            state.update_execution(eid, workflow_status="COMPLETED",
                                   current_stage="completed", finished_at=_now())
            state.log_event(eid, "workflow_completed", {"gate": "ok"})
            out["finalized"] = "COMPLETED"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if not reasons else 1
    finally:
        state.close()


# --------------------------------------------------------------- status
def cmd_status(args) -> int:
    """查节点/Agent 执行状态。"""
    cfg = load_config(args.project, strict=False)
    state = StateManager(args.db)
    try:
        eid = _resolve_execution_id(state, args.project, str(args.task_id))
        if args.node:
            disps = state.list_node_dispatches(eid)
            rows = [d for d in disps if d["node_id"] == args.node]
        else:
            rows = state.list_node_dispatches(eid)
        print(json.dumps({"execution_id": eid, "node_dispatches": rows},
                         ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        state.close()


# --------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dispatch.py",
                                description="DAG 派发统一入口（SQLite 唯一真相源）")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--project", required=True)
    p.add_argument("--task-id", required=True)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("plan", help="计算 DAG 可执行节点")
    sp.set_defaults(func=cmd_plan)

    sr = sub.add_parser("register-dispatch", help="事务登记 DISPATCHING + attempt_id")
    sr.add_argument("--node", required=True)
    sr.add_argument("--agent", required=True)
    sr.add_argument("--backend", choices=["claude_tool", "cli_subprocess"], default="claude_tool")
    sr.add_argument("--attempt-id", default="", help="自定义 attempt_id（默认自动生成）")
    sr.add_argument("--force-new-attempt", action="store_true",
                    help="人工确认后允许重派 UNVERIFIED/WAITING_HUMAN 节点")
    sr.set_defaults(func=cmd_register_dispatch)

    sc = sub.add_parser("confirm-running", help="主控取得 agent_id/pid 后确认 RUNNING")
    sc.add_argument("--node", required=True)
    sc.add_argument("--attempt", required=True)
    sc.add_argument("--agent-id", default="", help="CLAUDE_TOOL 返回的真实 agent_id")
    sc.add_argument("--pid", default="", help="CLI_SUBPROCESS 的 pid")
    sc.set_defaults(func=cmd_confirm_running)

    srr = sub.add_parser("record-result", help="记录节点执行结果")
    srr.add_argument("--node", required=True)
    srr.add_argument("--attempt", required=True)
    srr.add_argument("--status", required=True,
                     choices=["DONE", "FAILED", "BLOCKED", "UNVERIFIED", "WAITING_HUMAN"])
    srr.add_argument("--error-code", default="")
    srr.add_argument("--error", default="")
    srr.set_defaults(func=cmd_record_result)

    srec = sub.add_parser("reconcile", help="对账 DISPATCHING 超时/僵尸 RUNNING/迟到通知")
    srec.set_defaults(func=cmd_reconcile)

    se = sub.add_parser("export-state", help="从 SQLite 生成 run-state.json 只读快照")
    se.set_defaults(func=cmd_export_state)

    ss = sub.add_parser("status", help="查节点/Agent 执行状态")
    ss.add_argument("--node", default="")
    ss.set_defaults(func=cmd_status)

    sg = sub.add_parser("gate", help="统一终止门禁（全部节点 DONE 才允许结束）")
    sg.add_argument("--finalize", action="store_true",
                    help="门禁通过时把 execution 置为 COMPLETED")
    sg.set_defaults(func=cmd_gate)

    sf = sub.add_parser("flush-writes", help="重试 pending_writes（禅道回写队列）")
    sf.set_defaults(func=cmd_flush_writes)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyError as e:
        sys.stderr.write("[NOT_FOUND] %s\n" % e)
        return 3
    except ValueError as e:
        sys.stderr.write("[ERROR] %s\n" % e)
        return 1
    except Exception as e:
        sys.stderr.write("[ERROR] %s: %s\n" % (type(e).__name__, e))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
