# -*- coding: utf-8 -*-
"""P11.1 统一 CLI —— runner / monitor 命令入口。

命令：
    runner.py  run      --project P --task-id T [选项]   启动任务
    runner.py  status   --task-id T [--project P]        查看状态
    runner.py  history  --task-id T [--project P]        查看历史
    runner.py  list     [--project P]                    列出运行记录
    monitor.py --task-id T [--project P]                 监控信息
    monitor.py --list                                    全部任务健康

复用现有 AgentRunner / Monitor / StateManager / TaskRouter，**不重复实现业务逻辑**。
默认 `--dry-run` 之外的 `run` 才真正拉起子进程；测试用 `--dry-run` 不启动真实开发任务。
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from cli_util import (  # noqa: E402
    DEFAULT_DB,
    EXIT_BLOCKED,
    EXIT_FAILED,
    EXIT_LOCKED,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    configure_stdout,
    err,
    load_config,
    log,
    table,
    truncate,
    warn,
)
from models import (  # noqa: E402
    AgentState,
    ExecutionRun,
    TaskLevel,
    TaskState,
    WorkflowType,
)
from state_manager import StateManager  # noqa: E402
from task_router import TaskRouter, TaskSignal  # noqa: E402
from monitor import Monitor  # noqa: E402


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------- 通用参数
def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", default=DEFAULT_DB, help="状态库路径（默认 logs/agent_manager.db）")
    p.add_argument("--json", action="store_true", help="以 JSON 输出（便于脚本消费）")
    p.add_argument("--quiet", action="store_true", help="减少输出")


# --------------------------------------------------------------- runner: run
def _cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config()
    state = StateManager(args.db)
    try:
        project = args.project
        task = str(args.task_id)

        # 1) 路由分级
        signal = TaskSignal(
            file_count=args.files_count or 0,
            file_paths=(args.files or "").split(",") if args.files else [],
            description=args.description or "",
            affected_repos=(args.repos or "").split(",") if args.repos else [],
            business_complexity=args.complexity,
            user_no_subagents=bool(args.no_subagents),
            user_skip_build=bool(args.skip_build),
            user_static_only=bool(args.static_only),
        )
        if args.level:
            # 用户显式指定等级（覆盖自动分级）
            signal.business_complexity = {"S": "low", "M": "medium", "L": "high"}[args.level]
        router = TaskRouter(cfg)
        decision = router.classify(task, project, signal)

        if not args.quiet:
            log(f"任务分级: {decision.task_level.value}")
            log(f"分类理由: {decision.classification_reason}")
            log(f"工作流:   {decision.selected_workflow.value}")
            log(f"子 Agent: {decision.selected_agents or '（无）'}")
            log(f"预期测试: {decision.expected_tests}")
            log(f"耗时预算: {decision.execution_budget_seconds}s")

        # 2) 重复执行检查（任务锁）
        if not args.force and state.is_locked(project, task):
            err(f"任务 {project}/{task} 已有运行实例，禁止重复启动。用 --force 覆盖（谨慎）。")
            return EXIT_LOCKED

        # 3) 已完成任务检查（不重复执行禅道任务）
        prev = state.get_execution(project, task)
        if prev and prev.get("workflow_status") == TaskState.COMPLETED.value and not args.force:
            err(f"任务 {project}/{task} 已完成（result={prev.get('result')}），不重复执行。用 --force 覆盖。")
            return EXIT_BLOCKED

        # 4) 建执行记录
        run = ExecutionRun(
            project_key=project,
            task_id=task,
            task_level=decision.task_level,
            workflow_status=TaskState.RUNNING,
            current_stage="routing",
            started_at=_now(),
        )
        eid = state.create_execution(run)
        state.log_event(eid, "cli_run", decision.to_dict())
        if not args.quiet:
            log(f"执行记录: execution_id={eid}")

        # 5) dry-run：不启动真实子进程
        if args.dry_run:
            state.update_execution(
                eid,
                workflow_status=TaskState.COMPLETED,
                current_stage="dry-run",
                finished_at=_now(),
                result="DRY_RUN",
            )
            state.log_event(eid, "cli_dry_run_complete", {"decision": decision.to_dict()})
            log("[dry-run] 未启动真实开发任务（Mock 验证模式）")
            _print_summary(state, eid, args.json)
            return EXIT_OK

        # 6-9) Agent 执行（含自动重试）+ Verifier 验收
        #      五状态分离：Agent 进程/执行状态 ≠ 验收状态 ≠ 工作流状态 ≠ 外部回写状态；
        #      Agent exit code 0 只代表进程正常退出，**不直接认定任务完成**（须 Verifier）。
        workdir = args.workdir or os.getcwd()
        prompt = args.prompt or f"/zentao-dev-workflow {project} {task}"
        notifier = _build_notifier(cfg, state, args)
        agent_state, exit_code, report, attempt = _execute_with_retry(
            args, cfg, state, notifier, eid, project, task, decision, workdir, prompt,
        )
        agent_ok = agent_state == AgentState.SUCCEEDED
        v_ok, v_reason = report.passed()

        if not (agent_ok and v_ok):
            # 终态失败：验收失败/执行失败/重试超限。状态持久化 + 通知，上下文不丢。
            state.update_execution(
                eid,
                workflow_status=TaskState.FAILED,
                current_stage="finished",
                finished_at=_now(),
                result=f"agent={agent_state.value};verify={report.overall}",
                error_message=(v_reason or f"exit={exit_code}")[:300],
                retry_count=attempt - 1,
            )
            state.log_event(eid, "status_snapshot",
                            _status_snapshot(agent_state, exit_code, report, attempt,
                                             "none", TaskState.FAILED.value))
            state.log_event(eid, "cli_run_finished",
                            {"state": agent_state.value, "exit_code": exit_code,
                             "verify": report.overall, "attempt": attempt})
            _print_summary(state, eid, args.json)
            return EXIT_FAILED

        # 10) 工作流完成（Workflow Status）：Verifier 通过是唯一完成判定依据
        state.update_execution(
            eid,
            workflow_status=TaskState.COMPLETED,
            current_stage="verified",
            finished_at=_now(),
            result=f"agent={agent_state.value};verify={report.overall}",
            retry_count=attempt - 1,
        )

        # 11) 外部回写：Verifier 通过后自动 finish/done，失败入待写队列。
        provider_status = "skipped"
        if args.zentao_finish:
            provider_status = _zentao_finish_with_notify(args, state, notifier, eid, project, task)

        state.log_event(eid, "status_snapshot",
                        _status_snapshot(agent_state, exit_code, report, attempt,
                                         provider_status, TaskState.COMPLETED.value))
        state.log_event(eid, "cli_run_finished",
                        {"state": agent_state.value, "exit_code": exit_code,
                         "verify": report.overall, "attempt": attempt})
        notifier.final_success(project_key=project, task_id=task,
                               task_level=decision.task_level.value,
                               summary=f"验收通过 {report.overall}", commit=report.commit)
        _print_summary(state, eid, args.json)
        return EXIT_OK

    finally:
        state.close()


# --------------------------------------------------------------- 执行编排辅助
def _build_notifier(cfg: dict, state: StateManager, args: argparse.Namespace):
    """通知器：配置 notification.enabled 且未 --no-notify 时启用；通知失败不阻塞任务。"""
    from notifier import Notifier

    enabled = bool((cfg.get("notification", {}) or {}).get("enabled", True)) and not args.no_notify
    return Notifier(
        enabled=enabled,
        state=state,
        dry_run=bool(getattr(args, "dry_run", False)),
        logger=(lambda m: None if args.quiet else log),
    )


def _status_snapshot(agent_state: "AgentState", exit_code, report, attempt: int,
                     provider_status: str, workflow_status: str) -> dict:
    """五状态分离快照：Agent 进程 / Agent 执行 / 验收 / 工作流 / 外部 Provider。"""
    return {
        "agent_process_status": f"exit={exit_code}",
        "agent_execution_status": agent_state.value,
        "verification_status": report.overall,
        "workflow_status": workflow_status,
        "external_provider_status": provider_status,
        "attempt": attempt,
    }


def _execute_with_retry(args, cfg, state, notifier, eid, project, task, decision,
                        workdir: str, prompt: str):
    """Agent 执行 + Verifier 验收 + 自动重试循环。

    返回 (agent_state, exit_code, verify_report, attempt)。
    - Agent 进程成功 ≠ 任务完成：必须经 Verifier 判定
    - 失败经 RetryManager 分类决策（TRANSIENT 重试 / PERMANENT 交回 / HUMAN 中止）
    - 每次决策持久化到 execution_events；超过重试上限通知用户后终止
    """
    import time

    from retry import RetryManager, RetryPolicy
    from runner import AgentRunner
    from verifier import Verifier

    retry_mgr = RetryManager(RetryPolicy.from_config(cfg))
    attempt = 0
    while True:
        attempt += 1
        runner = AgentRunner(state, logger=(lambda m: None if args.quiet else log))
        try:
            agent_run = runner.start(
                project_key=project,
                task_id=task,
                prompt=prompt,
                workdir=workdir,
                execution_id=eid,
                agent_name="main",
                session_id=args.session_id or None,
                timeout_seconds=decision.execution_budget_seconds,
                attempt=attempt,
            )
        except Exception as e:
            state.log_event(eid, "cli_run_start_failed", {"error": str(e)[:200], "attempt": attempt})
            notifier.agent_start_failed(project_key=project, task_id=task,
                                        task_level=decision.task_level.value,
                                        summary=str(e)[:200])
            raise
        if attempt == 1:
            notifier.task_started(project_key=project, task_id=task,
                                  task_level=decision.task_level.value, stage="run")
        if not args.quiet:
            log(f"已启动 pid={agent_run.pid} attempt={attempt} workdir={workdir}")

        agent_state, exit_code, err_msg = AgentState.FAILED, None, ""
        try:
            agent_state, exit_code = runner.wait(timeout_seconds=decision.execution_budget_seconds)
        except Exception as e:
            err_msg = str(e)[:300]
            is_timeout = "超时" in err_msg or "timeout" in err_msg.lower()
            agent_state = AgentState.TIMEOUT if is_timeout else AgentState.FAILED
            if is_timeout:
                notifier.agent_timeout(project_key=project, task_id=task,
                                       task_level=decision.task_level.value, summary=err_msg)
            else:
                notifier.agent_crashed(project_key=project, task_id=task,
                                       task_level=decision.task_level.value, summary=err_msg)

        # 验收（Verification Status）：Verifier 是任务完成的唯一判定依据
        state.update_execution(eid, current_stage="verifying")
        report = Verifier(workdir=workdir).verify(require_commit=True)
        state.save_verification(eid, report.checks)
        v_ok, v_reason = report.passed()
        state.log_event(eid, "verification",
                        {"overall": report.overall, "passed": v_ok, "reason": v_reason})
        if not args.quiet:
            log(f"验收: overall={report.overall} passed={v_ok}（{v_reason}）")

        agent_ok = agent_state == AgentState.SUCCEEDED and not err_msg
        if agent_ok and v_ok:
            return agent_state, exit_code, report, attempt

        # 失败 → RetryManager 决策（含副作用检查：已 commit 不盲目重试）
        error = err_msg or f"agent_state={agent_state.value} exit={exit_code} verify={report.overall}"
        precheck = {"already_committed": bool(report.commit)}
        action, delay, rec = retry_mgr.decide(attempt=attempt, error=error, precheck=precheck)
        state.log_event(eid, "retry_decision", rec.to_dict())

        if not agent_ok and agent_state == AgentState.TIMEOUT:
            pass  # 已通知
        elif agent_ok and not v_ok:
            notifier.qa_failed(project_key=project, task_id=task,
                               task_level=decision.task_level.value, summary=v_reason[:200])
        if action != "retry":
            if action == "abort":
                notifier.final_failure(project_key=project, task_id=task,
                                       task_level=decision.task_level.value,
                                       summary=f"重试终止: {rec.reason[:200]}")
            else:  # hand_to_main
                notifier.human_needed(project_key=project, task_id=task,
                                      task_level=decision.task_level.value,
                                      summary=f"需人工介入: {rec.reason[:200]}")
            return agent_state, exit_code, report, attempt

        if not args.quiet:
            log(f"自动重试 {attempt}→{attempt + 1}（{rec.reason[:80]}），退避 {delay:.0f}s")
        notifier.auto_retry(project_key=project, task_id=task,
                            task_level=decision.task_level.value,
                            summary=f"第 {attempt} 次失败自动重试: {rec.reason[:160]}")
        state.update_execution(eid, retry_count=attempt)
        time.sleep(delay)


def _zentao_finish_with_notify(args, state, notifier, eid, project, task) -> str:
    """Verifier 通过后自动回写禅道 finish/done。工时/日期由调用方提供，失败入待写队列，不改执行结果。
    """
    from zentao_reporter import ZenTaoReporter

    if args.consumed is None or args.left is None or not args.finished_date:
        warn("--zentao-finish 需要 --consumed/--left/--finished-date（不推算工时与日期），本次跳过回写")
        return "skipped_missing_fields"
    zr = ZenTaoReporter(state, dry_run=bool(args.dry_run),
                        logger=(lambda m: None if args.quiet else log))
    try:
        r = zr.finish(
            task_id=task,
            project_key=project,
            verifier_passed=True,
            consumed=args.consumed,
            left=args.left,
            finished_date=args.finished_date,
            real_started=args.real_started or None,
            exec_id=str(eid),
        )
        if r.get("ok"):
            return "success"
        notifier.zentao_write_failed(project_key=project, task_id=task,
                                     summary=str(r.get("reason", "读回未确认"))[:200])
        return "readback_mismatch"
    except Exception as e:
        # 失败已入待写队列（flush_pending 可重试）；不伪造成功，不改任务执行结果
        notifier.zentao_write_failed(project_key=project, task_id=task, summary=str(e)[:200])
        return "failed_queued"


# --------------------------------------------------------------- runner: status
def _cmd_status(args: argparse.Namespace) -> int:
    state = StateManager(args.db)
    try:
        if args.project:
            rec = state.get_execution(args.project, str(args.task_id))
        else:
            # 未给 project → 跨项目查最近
            rec = None
            for e in state.list_executions():
                if str(e.get("task_id")) == str(args.task_id):
                    rec = e
                    break
        if not rec:
            err(f"未找到任务记录: {args.task_id}")
            return EXIT_NOT_FOUND

        if args.json:
            import json

            out = dict(rec)
            out["agent_runs"] = state.get_agent_runs(rec["id"])
            print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
            return EXIT_OK

        log(f"任务:     {rec.get('project_key')}/{rec.get('task_id')}")
        log(f"等级:     {rec.get('task_level')}")
        log(f"状态:     {rec.get('workflow_status')}")
        log(f"阶段:     {rec.get('current_stage')}")
        log(f"结果:     {rec.get('result')}")
        log(f"开始:     {rec.get('started_at')}")
        log(f"结束:     {rec.get('finished_at')}")
        log(f"重试:     {rec.get('retry_count')}")
        if rec.get("error_message"):
            log(f"错误:     {truncate(rec['error_message'], 120)}")

        agents = state.get_agent_runs(rec["id"])
        if agents:
            log("")
            log("Agent 运行:")
            log(table(
                [[a.get("agent_name", ""), str(a.get("pid", "")), a.get("status", ""),
                  truncate(str(a.get("exit_code", "")), 8)] for a in agents],
                ["agent", "pid", "status", "exit"],
            ))
        return EXIT_OK
    finally:
        state.close()


# --------------------------------------------------------------- runner: history
def _cmd_history(args: argparse.Namespace) -> int:
    state = StateManager(args.db)
    try:
        recs = [e for e in state.list_executions(args.project) if str(e.get("task_id")) == str(args.task_id)]
        if args.project is None:
            recs = [e for e in state.list_executions() if str(e.get("task_id")) == str(args.task_id)]
        if not recs:
            err(f"无历史记录: {args.task_id}")
            return EXIT_NOT_FOUND

        if args.json:
            import json

            print(json.dumps(recs, ensure_ascii=False, indent=2, default=str))
            return EXIT_OK

        log(f"任务 {args.task_id} 历史（{len(recs)} 条）:")
        log(table(
            [[str(e.get("id", "")), str(e.get("task_level", "")), str(e.get("workflow_status", "")),
              str(e.get("result", "")), truncate(str(e.get("started_at", "")), 19),
              truncate(str(e.get("error_message", "")), 30)] for e in recs],
            ["id", "level", "status", "result", "started", "error"],
        ))
        return EXIT_OK
    finally:
        state.close()


# --------------------------------------------------------------- runner: list
def _cmd_list(args: argparse.Namespace) -> int:
    state = StateManager(args.db)
    try:
        recs = state.list_executions(args.project)
        if not recs:
            log("无执行记录")
            return EXIT_OK
        if args.json:
            import json

            print(json.dumps(recs, ensure_ascii=False, indent=2, default=str))
            return EXIT_OK
        log(f"执行记录（{len(recs)} 条）:")
        log(table(
            [[str(e.get("id", "")), str(e.get("project_key", "")), str(e.get("task_id", "")),
              str(e.get("task_level", "")), str(e.get("workflow_status", "")),
              str(e.get("result", "")), truncate(str(e.get("started_at", "")), 19)] for e in recs],
            ["id", "project", "task", "level", "status", "result", "started"],
        ))
        return EXIT_OK
    finally:
        state.close()


# --------------------------------------------------------------- monitor
def _cmd_monitor(args: argparse.Namespace) -> int:
    cfg = load_config()
    state = StateManager(args.db)
    try:
        if args.list:
            return _monitor_list(state, args)

        if not args.task_id:
            err("需要 --task-id（或使用 --list 查看全部）")
            return EXIT_USAGE

        rec = None
        if args.project:
            rec = state.get_execution(args.project, str(args.task_id))
        else:
            for e in state.list_executions():
                if str(e.get("task_id")) == str(args.task_id):
                    rec = e
                    break
        if not rec:
            err(f"未找到任务记录: {args.task_id}")
            return EXIT_NOT_FOUND

        agents = state.get_agent_runs(rec["id"])
        live = state.find_live_agent(rec["id"])

        mcfg = cfg.get("monitor", {})
        mon = Monitor(
            poll_interval_seconds=float(mcfg.get("poll_interval_seconds", 5)),
            heartbeat_timeout_seconds=float(mcfg.get("heartbeat_timeout_seconds", 300)),
            default_task_timeout_seconds=float(mcfg.get("default_task_timeout_seconds", 1800)),
            output_idle_warning_seconds=float(mcfg.get("output_idle_warning_seconds", 300)),
        )
        snap = mon.snapshot(
            pid=live.get("pid") if live else None,
            started_at=rec.get("started_at"),
            last_output_at=live.get("last_output_at") if live else None,
            stage=rec.get("current_stage") or "",
        )
        kill, reason = mon.should_kill(snap)

        payload = {
            "task": f"{rec.get('project_key')}/{rec.get('task_id')}",
            "workflow_status": rec.get("workflow_status"),
            "current_stage": rec.get("current_stage"),
            "result": rec.get("result"),
            "health": snap.to_dict(),
            "should_kill": kill,
            "kill_reason": reason,
            "agent_runs": agents,
        }
        if args.json:
            import json

            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return EXIT_OK

        log(f"任务:       {payload['task']}")
        log(f"工作流状态: {payload['workflow_status']}")
        log(f"当前阶段:   {payload['current_stage']}")
        log(f"结果:       {payload['result']}")
        log("")
        log("健康快照（四概念分离）:")
        log(f"  Process Alive    : {snap.process_alive}")
        log(f"  Heartbeat        : {snap.heartbeat}")
        log(f"  Output Activity  : {snap.output_idle_seconds}s 静默")
        log(f"  Workflow Progress: {snap.workflow_progress or '—'}")
        log(f"  已耗时           : {int(snap.elapsed_seconds)}s")
        log(f"  应终止           : {kill}" + (f"（{reason}）" if reason else ""))
        for w in snap.warnings:
            warn(w)
        if agents:
            log("")
            log("Agent 运行:")
            log(table(
                [[a.get("agent_name", ""), str(a.get("pid", "")), a.get("status", ""),
                  truncate(str(a.get("last_output_at", "")), 19)] for a in agents],
                ["agent", "pid", "status", "last_output"],
            ))
        return EXIT_OK
    finally:
        state.close()


def _monitor_list(state: StateManager, args: argparse.Namespace) -> int:
    recs = state.list_executions(args.project)
    cfg = load_config()
    mcfg = cfg.get("monitor", {})
    mon = Monitor(
        default_task_timeout_seconds=float(mcfg.get("default_task_timeout_seconds", 1800)),
        output_idle_warning_seconds=float(mcfg.get("output_idle_warning_seconds", 300)),
    )
    rows = []
    for e in recs:
        live = state.find_live_agent(e["id"])
        snap = mon.snapshot(
            pid=live.get("pid") if live else None,
            started_at=e.get("started_at"),
            last_output_at=live.get("last_output_at") if live else None,
        )
        rows.append([
            str(e.get("id", "")),
            f"{e.get('project_key')}/{e.get('task_id')}",
            str(e.get("workflow_status", "")),
            "alive" if snap.process_alive else "down",
            snap.heartbeat,
            f"{int(snap.elapsed_seconds)}s",
        ])
    if args.json:
        import json

        print(json.dumps([dict(zip(["id", "task", "status", "process", "heartbeat", "elapsed"], r)) for r in rows],
                         ensure_ascii=False, indent=2))
        return EXIT_OK
    if not rows:
        log("无执行记录")
        return EXIT_OK
    log(f"任务健康（{len(rows)} 条）:")
    log(table(rows, ["id", "task", "status", "process", "heartbeat", "elapsed"]))
    return EXIT_OK


# --------------------------------------------------------------- waiting（T12）
def _cmd_waiting(args: argparse.Namespace) -> int:
    """列出等待人工决策的任务（HITL WAITING_HUMAN / 决策 WAITING_REPLY）。"""
    state = StateManager(args.db)
    try:
        recs = [e for e in state.list_executions(args.project)
                if str(e.get("workflow_status")) == "WAITING_HUMAN"]
        # 同时查 HITL 决策层
        hitl_waiting = []
        try:
            from human_decision.decision_store import DecisionStore
            hs = DecisionStore()
            hitl_waiting = [d.to_dict() if hasattr(d, "to_dict") else d for d in hs.list_waiting()]
        except Exception:
            pass

        if args.json:
            import json
            print(json.dumps({"tasks": recs, "hitl_decisions": hitl_waiting},
                             ensure_ascii=False, indent=2, default=str))
            return EXIT_OK
        if not recs and not hitl_waiting:
            log("无等待人工决策的任务")
            return EXIT_OK
        if recs:
            log(f"任务级 WAITING_HUMAN（{len(recs)} 条）:")
            log(table([[str(e.get("id", "")), f"{e.get('project_key')}/{e.get('task_id')}",
                        truncate(str(e.get("current_stage", "")), 20)] for e in recs],
                      ["id", "task", "stage"]))
        if hitl_waiting:
            log("")
            log(f"HITL 决策等待（{len(hitl_waiting)} 条）:")
            log(table([[str(d.get("decision_id", "")), str(d.get("task_id", "")),
                        truncate(str(d.get("question", "")), 30)] for d in hitl_waiting],
                      ["decision_id", "task", "question"]))
        return EXIT_OK
    finally:
        state.close()


def _cmd_failures(args: argparse.Namespace) -> int:
    """列出失败任务及原因（T12）。"""
    state = StateManager(args.db)
    try:
        recs = [e for e in state.list_executions(args.project)
                if str(e.get("workflow_status")) in ("FAILED", "BLOCKED")]
        if args.json:
            import json
            print(json.dumps(recs, ensure_ascii=False, indent=2, default=str))
            return EXIT_OK
        if not recs:
            log("无失败任务")
            return EXIT_OK
        log(f"失败/阻塞任务（{len(recs)} 条）:")
        log(table([[str(e.get("id", "")), f"{e.get('project_key')}/{e.get('task_id')}",
                    str(e.get("workflow_status", "")), truncate(str(e.get("error_message", "")), 40)]
                   for e in recs], ["id", "task", "status", "error"]))
        return EXIT_OK
    finally:
        state.close()


# --------------------------------------------------------------- 摘要
def _print_summary(state: StateManager, eid: int, as_json: bool) -> None:
    events = state.get_events(eid)
    if as_json:
        import json

        print(json.dumps({"execution_id": eid, "events": len(events)}, ensure_ascii=False))
        return
    log(f"事件数: {len(events)}")


# --------------------------------------------------------------- 参数构造
def build_runner_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="runner.py",
        description="Agent Execution Manager — 任务启动与状态查询",
    )
    sub = p.add_subparsers(dest="command")

    # run
    pr = sub.add_parser("run", help="启动任务")
    pr.add_argument("--project", required=True, help="项目标识（config/projects/{key}.yaml）")
    pr.add_argument("--task-id", required=True, help="任务 ID")
    pr.add_argument("--workdir", default="", help="工作目录（默认当前目录）")
    pr.add_argument("--prompt", default="", help="自定义 prompt（默认 /zentao-dev-workflow {p} {t}）")
    pr.add_argument("--session-id", default="", help="恢复的 Claude Code session id")
    pr.add_argument("--level", choices=["S", "M", "L"], help="显式指定任务等级（覆盖自动分级）")
    pr.add_argument("--description", default="", help="任务描述（用于分级）")
    pr.add_argument("--files", default="", help="逗号分隔的文件路径（用于分级）")
    pr.add_argument("--files-count", type=int, default=0, help="影响文件数")
    pr.add_argument("--repos", default="", help="逗号分隔的受影响仓库")
    pr.add_argument("--complexity", choices=["low", "medium", "high"], default="low", help="业务复杂度")
    pr.add_argument("--no-subagents", action="store_true", help="不使用子 Agent（用户指令优先）")
    pr.add_argument("--skip-build", action="store_true", help="跳过 Build（用户指令优先）")
    pr.add_argument("--static-only", action="store_true", help="仅静态检查（用户指令优先）")
    pr.add_argument("--dry-run", action="store_true", help="Mock 模式：不启动真实开发任务")
    pr.add_argument("--force", action="store_true", help="覆盖重复/已完成检查（谨慎）")
    pr.add_argument("--zentao-finish", action="store_true",
                    help="Verifier 通过后自动回写禅道 finish/done（需提供 --consumed/--left/--finished-date）")
    pr.add_argument("--consumed", type=float, default=None, help="已消耗工时（finish 回写用，不推算）")
    pr.add_argument("--left", type=float, default=None, help="剩余工时（finish 回写用，不推算）")
    pr.add_argument("--finished-date", default="", help="实际完成日期 YYYY-MM-DD（finish 回写用）")
    pr.add_argument("--real-started", default="", help="实际开始日期 YYYY-MM-DD（finish 时回填）")
    pr.add_argument("--no-notify", action="store_true", help="不发送钉钉通知")
    _add_common(pr)

    # status
    ps = sub.add_parser("status", help="查看任务状态")
    ps.add_argument("--task-id", required=True)
    ps.add_argument("--project", default=None)
    _add_common(ps)

    # history
    ph = sub.add_parser("history", help="查看历史记录")
    ph.add_argument("--task-id", required=True)
    ph.add_argument("--project", default=None)
    _add_common(ph)

    # list
    pl = sub.add_parser("list", help="列出执行记录")
    pl.add_argument("--project", default=None)
    _add_common(pl)

    # waiting（T12：等待人工决策的任务）
    pw = sub.add_parser("waiting", help="列出等待人工决策的任务")
    pw.add_argument("--project", default=None)
    _add_common(pw)

    # failures（T12：最近失败原因）
    pf = sub.add_parser("failures", help="列出失败任务及原因")
    pf.add_argument("--project", default=None)
    _add_common(pf)

    return p


def build_monitor_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="monitor.py",
        description="Agent Execution Manager — 运行监控",
    )
    p.add_argument("--task-id", default=None, help="任务 ID")
    p.add_argument("--project", default=None, help="项目标识")
    p.add_argument("--list", action="store_true", help="列出全部任务健康")
    p.add_argument("--watch", action="store_true", help="持续监控（保留参数，当前单次快照）")
    _add_common(p)
    return p


# --------------------------------------------------------------- 入口
def runner_main(argv: Optional[list[str]] = None) -> int:
    configure_stdout()
    parser = build_runner_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return {
            "run": _cmd_run,
            "status": _cmd_status,
            "history": _cmd_history,
            "list": _cmd_list,
            "waiting": _cmd_waiting,
            "failures": _cmd_failures,
        }[args.command](args)
    except KeyboardInterrupt:
        err("已中断")
        return EXIT_FAILED
    except Exception as e:
        err(f"{type(e).__name__}: {e}")
        return EXIT_FAILED


def monitor_main(argv: Optional[list[str]] = None) -> int:
    configure_stdout()
    parser = build_monitor_parser()
    args = parser.parse_args(argv)
    if not args.task_id and not args.list:
        parser.print_help()
        return EXIT_USAGE
    try:
        return _cmd_monitor(args)
    except KeyboardInterrupt:
        err("已中断")
        return EXIT_FAILED
    except Exception as e:
        err(f"{type(e).__name__}: {e}")
        return EXIT_FAILED
