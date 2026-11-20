# -*- coding: utf-8 -*-
"""P11 Phase 6 — 集成测试（纯 Mock，不依赖生产禅道/Jenkins/业务环境）。

覆盖 P11 §十三 Phase 6 的关键场景：
    1  简单任务不启动 Subagent
    2  中等任务选择性启动 Agent
    3  复杂任务执行完整流程
    5  Agent 异常退出 / 6 超时 / 7 取消
    8  瞬时错误自动重试 / 9 代码错误不盲目重试
    11 重复 task_id 不重复启动
    12 Verifier 拒绝错误的成功状态
    13 BLOCKED 正确聚合
    15 钉钉重复事件去重
    16 Jenkins Job 白名单有效
    17 用户要求跳过 Build 时不启动 Build

运行：python -I agent-manager/tests/run_tests.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_AM = os.path.dirname(_HERE)
for p in (_AM, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from models import FaultClass, TaskLevel, VerifyStatus, WorkflowType  # noqa: E402
from task_router import TaskRouter, TaskSignal  # noqa: E402
from state_manager import StateManager  # noqa: E402
from retry import RetryManager, RetryPolicy, classify_fault  # noqa: E402
from verifier import TestSpec, Verifier, aggregate_blocked  # noqa: E402
from notifier import Notifier  # noqa: E402
from jenkins_adapter import JenkinsAdapter  # noqa: E402
from monitor import Monitor  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, PASS if cond else FAIL, detail))
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# --------------------------------------------------------------- 1-3 路由
def test_routing() -> None:
    section("1-3 任务分级与派发")
    rt = TaskRouter()

    # 1 简单任务不启动 Subagent
    d = rt.classify("T1", "demo", TaskSignal(
        file_count=1, description="修改按钮文案 css 样式",
        file_paths=["src/views/Button.vue"],
    ))
    check("1 简单任务 0 Subagent", d.task_level == TaskLevel.S and d.selected_agents == [],
          f"level={d.task_level.value} agents={d.selected_agents}")
    check("1 简单任务 workflow=direct", d.selected_workflow == WorkflowType.DIRECT)

    # 2 中等任务选择性启动
    d2 = rt.classify("T2", "demo", TaskSignal(
        file_count=6, description="修改薪酬模块业务逻辑",
        file_paths=["src/views/a.vue", "src/api/b.ts", "src/views/c.vue"],
        business_complexity="medium",
    ))
    check("2 中等任务 M 级", d2.task_level == TaskLevel.M)
    check("2 中等任务选择性 Agent", 0 < len(d2.selected_agents) < 7,
          f"agents={d2.selected_agents}")

    # 3 复杂任务完整流程
    d3 = rt.classify("T3", "demo", TaskSignal(
        file_count=12, description="跨仓库新增薪酬审批 DDL 接口契约",
        affected_repos=["sanitation", "web", "app"],
        touches_db=True, touches_api=True, cross_repo=True,
        business_complexity="high",
    ))
    check("3 复杂任务 L 级", d3.task_level == TaskLevel.L)
    check("3 L 级 workflow=full", d3.selected_workflow == WorkflowType.FULL)
    check("3 L 级含 architect/qa/ir", {
        "dw-architect", "dw-qa-engineer", "dw-integration-reviewer"
    }.issubset(set(d3.selected_agents)), f"agents={d3.selected_agents}")


# --------------------------------------------------------------- 风险升级
def test_risk_escalation() -> None:
    section("高风险单文件不归 S")
    rt = TaskRouter()
    d = rt.classify("T4", "demo", TaskSignal(
        file_count=1, description="修复越权审批漏洞", touches_security=True,
        file_paths=["src/x.vue"],
    ))
    check("安全风险升级（非 S）", d.task_level != TaskLevel.S, f"level={d.task_level.value}")

    d2 = rt.classify("T5", "demo", TaskSignal(
        file_count=1, description="改数据库表结构", touches_db=True, file_paths=["a.java"],
    ))
    check("DB 变更升级（非 S）", d2.task_level != TaskLevel.S, f"level={d2.task_level.value}")


# --------------------------------------------------------------- 用户指令优先
def test_user_override() -> None:
    section("4/17 用户指令优先")
    rt = TaskRouter()

    d = rt.classify("T6", "demo", TaskSignal(
        file_count=15, description="重构", user_no_subagents=True,
    ))
    check("用户禁止子 Agent → 0 agent", d.selected_agents == [],
          f"agents={d.selected_agents} workflow={d.selected_workflow.value}")
    check("用户禁止子 Agent → direct", d.selected_workflow == WorkflowType.DIRECT)

    d2 = rt.classify("T7", "demo", TaskSignal(
        file_count=2, description="改样式", user_skip_build=True,
    ))
    check("17 用户跳过 Build → tests 无 build", "build" not in d2.expected_tests,
          f"tests={d2.expected_tests}")

    d3 = rt.classify("T8", "demo", TaskSignal(
        file_count=2, description="改样式", user_static_only=True,
    ))
    check("用户只做静态检查", all(t in ("static", "lint") for t in d3.expected_tests),
          f"tests={d3.expected_tests}")


# --------------------------------------------------------------- 11 任务锁
def test_task_lock() -> None:
    section("11 重复 task_id 不重复启动")
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    sm = StateManager(db)
    ok1 = sm.acquire_lock("demo", "T1", os.getpid())
    ok2 = sm.acquire_lock("demo", "T1", os.getpid())
    check("首次获取锁", ok1 is True)
    check("11 重复启动被拒", ok2 is False, "第二次 acquire 返回 False")
    check("is_locked=True", sm.is_locked("demo", "T1"))
    sm.release_lock("demo", "T1")
    check("释放后可再获取", sm.acquire_lock("demo", "T1", os.getpid()) is True)
    sm.close()


# --------------------------------------------------------------- 5/6/7 Agent 生命周期
def test_agent_lifecycle() -> None:
    section("5/6/7 Agent 生命周期（超时/取消/异常）")
    m = Monitor(default_task_timeout_seconds=1, output_idle_warning_seconds=0.5)

    # 进程存活判定
    check("Process Alive（自身进程）", m.snapshot(pid=os.getpid(), started_at=None, last_output_at=None).process_alive)

    # 无心跳源 → unavailable（不伪造）
    snap = m.snapshot(pid=os.getpid(), started_at=None, last_output_at=None)
    check("Heartbeat=unavailable（不伪造）", snap.heartbeat == "unavailable")

    # 6 超时应杀（阶段超时）
    import datetime
    old = (datetime.datetime.now().astimezone() - datetime.timedelta(seconds=100)).isoformat(timespec="seconds")
    kill, reason = m.should_kill(snap, stage_timeout_seconds=10, stage_started_at=old)
    check("6 阶段超时 → 应终止", kill is True, reason)

    # 输出静默**不**杀进程
    snap2 = Monitor(output_idle_warning_seconds=0).snapshot(
        pid=os.getpid(), started_at=None,
        last_output_at=(datetime.datetime.now().astimezone() - datetime.timedelta(seconds=999)).isoformat(timespec="seconds"),
    )
    kill2, _ = m.should_kill(snap2)
    check("输出静默不杀进程", kill2 is False,
          f"warnings={snap2.warnings[:1]}")


# --------------------------------------------------------------- 8/9 重试
def test_retry() -> None:
    section("8/9 重试与故障分类")
    check("网络重置→TRANSIENT", classify_fault("Connection reset by peer") == FaultClass.TRANSIENT)
    check("超时→TRANSIENT", classify_fault("timed out") == FaultClass.TRANSIENT)
    check("测试失败→PERMANENT", classify_fault("AssertionError: test failed") == FaultClass.PERMANENT)
    check("ESLint→PERMANENT", classify_fault("eslint 3 errors") == FaultClass.PERMANENT)
    check("取消→HUMAN", classify_fault("user cancelled") == FaultClass.HUMAN)

    rm = RetryManager(RetryPolicy(max_attempts=2, initial_delay_seconds=0))

    # 8 瞬时错误自动重试
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("Connection reset")
        return "ok"

    out = rm.run(flaky, max_attempts=2)
    check("8 瞬时错误自动重试成功", out == "ok" and calls["n"] == 2, f"calls={calls['n']}")

    # 9 代码错误不盲目重试
    calls2 = {"n": 0}

    def broken():
        calls2["n"] += 1
        raise RuntimeError("AssertionError: test failed")

    try:
        rm.run(broken, max_attempts=3)
        check("9 代码错误不重试", False, "未抛出")
    except Exception as e:
        check("9 代码错误不盲目重试", calls2["n"] == 1 and "Main Agent" in str(e),
              f"calls={calls2['n']} err={str(e)[:40]}")

    # 有副作用不重试
    act, _, _ = rm.decide(attempt=1, error="timeout", precheck={"has_side_effects": True})
    check("有副作用 → 交回 Main", act == "hand_to_main")

    # 超上限
    act2, _, _ = rm.decide(attempt=5, error="timeout")
    check("超重试上限 → abort", act2 == "abort")


# --------------------------------------------------------------- 12/13 Verifier
def test_verifier() -> None:
    section("12/13 Verifier 拒绝错误成功 + BLOCKED 聚合")
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=d, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=d, capture_output=True)
    open(os.path.join(d, "a.txt"), "w").write("x")
    subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=d, capture_output=True)

    v = Verifier(workdir=d)
    rep = v.verify(
        allowed_files=["a.txt"],
        test_specs=[
            TestSpec(name="lint", cmd=[sys.executable, "-c", "print('ok')"], workdir=d),
            TestSpec(name="unit", cmd=[sys.executable, "-c", "import sys;sys.exit(1)"], workdir=d),
            TestSpec(name="e2e", blocked_reason="需浏览器+后端"),
            TestSpec(name="api", blocked_reason="需后端服务"),
            TestSpec(name="build", user_skipped=True),
            TestSpec(name="notrun"),
        ],
        requirement_checks=[("FR1", True, "已实现")],
    )

    check("12 单元测试 FAIL 不算成功", rep.tests["unit"] == VerifyStatus.FAIL)
    check("12 overall 非 SUCCESS", rep.overall != "SUCCESS", f"overall={rep.overall}")
    check("12 BLOCKED 不算 PASS", rep.tests["e2e"].is_passable() is False)
    check("12 SKIPPED 不算 PASS", rep.tests["build"].is_passable() is False)
    check("12 NOT_RUN 不算 PASS", rep.tests["notrun"].is_passable() is False)
    check("13 BLOCKED 已聚合", rep.blocked_summary is not None and "环境阻塞" in rep.blocked_summary,
          (rep.blocked_summary or "")[:60].replace("\n", " "))

    # 铁律逐项
    for st in VerifyStatus:
        expect = (st == VerifyStatus.PASS)
        check(f"铁律 {st.value}.is_passable()=={expect}", st.is_passable() == expect)

    # 越权检测
    open(os.path.join(d, "HACK.txt"), "w").write("x")
    subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "hack"], cwd=d, capture_output=True)
    r2 = v.verify(allowed_files=["a.txt"], test_specs=[])
    check("越权修改被拒", r2.git_status == VerifyStatus.FAIL, r2.checks[0].evidence[:50])


# --------------------------------------------------------------- 15 钉钉去重
def test_notifier() -> None:
    section("15 钉钉重复事件去重")
    n = Notifier(enabled=True, dry_run=True)
    r1 = n.notify(project_key="p", task_id="3413", event_type="task_started", summary="开始")
    r2 = n.notify(project_key="p", task_id="3413", event_type="task_started", summary="开始")
    check("15 相同事件去重", r1.get("sent") is True and r2.get("deduped") is True)
    r3 = n.notify(project_key="p", task_id="3413", event_type="qa_done", summary="QA")
    check("不同事件不误去重", r3.get("sent") is True)

    n2 = Notifier(enabled=True, dry_run=False)
    n2._send_via_ccconnect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("模拟失败"))
    r4 = n2.notify(project_key="p", task_id="1", event_type="final_failure", summary="x")
    check("通知失败不阻塞任务", r4.get("sent") is False and "error" in r4)


# --------------------------------------------------------------- 16 Jenkins 白名单
def test_jenkins() -> None:
    section("16 Jenkins Job 白名单")
    ja = JenkinsAdapter(enabled=True, mock=True, allowed_prefix="ai-test-")
    check("ai-test-* 允许", ja.is_allowed("ai-test-runner") is True)
    check("生产 Job 拒绝", ja.is_allowed("ct-jeebootx-sanitation") is False)
    check("jeebootx-ui 拒绝", ja.is_allowed("jeebootx-ui") is False)

    try:
        ja.trigger(job="ct-jeebootx-sanitation", project_key="p", task_id="1")
        check("触发生产 Job 被拒", False, "未抛出")
    except Exception as e:
        check("触发生产 Job 被拒", "白名单" in str(e), str(e)[:40])

    r = ja.trigger(job="ai-test-runner", project_key="p", task_id="1")
    check("Mock 模式不计为通过", r["verify_status"] != VerifyStatus.PASS.value,
          f"verify_status={r['verify_status']}")


# --------------------------------------------------------------- 状态持久化/恢复
def test_state_recovery() -> None:
    section("状态持久化与断点恢复")
    from models import AgentRun, AgentState, ExecutionRun, VerifyCheck

    db = os.path.join(tempfile.mkdtemp(), "r.db")
    sm = StateManager(db)
    eid = sm.create_execution(ExecutionRun(project_key="demo", task_id="T1", task_level=TaskLevel.S))
    sm.create_agent_run(AgentRun(execution_id=eid, agent_name="dw-qa-engineer", pid=99999, status=AgentState.RUNNING))
    sm.save_verification(eid, [VerifyCheck("lint", VerifyStatus.PASS, "0 err")])
    sm.enqueue_pending_write("demo", "T1", "progress", {"text": "x"})
    sm.log_event(eid, "checkpoint", {"stage": "QA1"})

    # 新实例读取（模拟管理器重启）
    sm2 = StateManager(db)
    got = sm2.get_execution("demo", "T1")
    check("恢复执行状态", got is not None and got["task_level"] == "S")
    check("恢复 Agent 记录", len(sm2.get_agent_runs(eid)) == 1)
    check("恢复验证结果", len(sm2.get_verification(eid)) == 1)
    check("待写队列不丢", len(sm2.get_pending_writes("T1")) == 1)
    check("事件流完整", len(sm2.get_events(eid)) >= 2)
    check("识别运行中 Agent", sm2.find_live_agent(eid) is not None)
    sm.close()
    sm2.close()




# --------------------------------------------------------------- 禅道状态流转策略
def test_zentao_finish_policy() -> None:
    section("禅道 task_finish/task_close 策略")
    from zentao_reporter import ZenTaoReporter

    z = ZenTaoReporter(dry_run=True)

    # task_finish：Verifier 门禁通过后自动
    ok, _ = z.can_finish(verifier_passed=True, consumed=8, left=0)
    check("门禁通过 → 允许 task_finish", ok is True)

    ok2, _ = z.can_finish(verifier_passed=False, human_confirmed=False, consumed=8, left=0)
    check("门禁未过+无人工 → 拒绝 task_finish", ok2 is False)

    ok3, _ = z.can_finish(verifier_passed=False, human_confirmed=True, consumed=8, left=0)
    check("人工确认可兜底 task_finish", ok3 is True)

    ok4, r4 = z.can_finish(verifier_passed=True, consumed=None, left=None)
    check("缺工时 → 拒绝（不推算）", ok4 is False and "不推算" in r4)

    # task_close：按关闭条件判断，不满足则暂缓
    ok5, r5 = z.can_close(task_detail={"status": "done"}, verifier_passed=True)
    check("关闭条件满足 → 允许 task_close", ok5 is True)

    ok6, r6 = z.can_close(task_detail={"status": "doing"}, verifier_passed=True)
    check("禅道状态非 done → 暂缓关闭", ok6 is False and "done" in r6)

    ok7, r7 = z.can_close(task_detail={"status": "done"}, verifier_passed=False)
    check("验收未过 → 暂缓关闭", ok7 is False and "验收" in r7)

    ok8, _ = z.can_close(task_detail={"status": "done"}, verifier_passed=True, deliverables_ok=False)
    check("交付未完成 → 暂缓关闭", ok8 is False)

    ok9, _ = z.can_close(task_detail={"status": "done"}, verifier_passed=True, records_ok=False)
    check("记录缺失 → 暂缓关闭", ok9 is False)

    ok10, _ = z.can_close(task_detail={"status": "closed"}, verifier_passed=True)
    check("已 closed → 幂等放行", ok10 is True)

    # 暂缓关闭必须记录具体原因
    d = z.close_deferred(task_id="T1", project_key="p", reason="验收未通过")
    check("暂缓关闭记录原因", d["ok"] is False and d.get("deferred") is True and "验收未通过" in d["reason"])

    # close 成功路径（dry_run，含读回确认语义）
    r11 = z.close(task_id="T1", project_key="p", comment="交付完成，关闭",
                  verifier_passed=True, task_detail={"status": "done"})
    check("关闭条件满足 → 自动 close（dry_run）", r11["ok"] is True)

    # close 条件不满足 → 暂缓，不执行
    r12 = z.close(task_id="T1", project_key="p", comment="x",
                  verifier_passed=False, task_detail={"status": "done"})
    check("关闭条件不满足 → 暂缓不执行", r12["ok"] is False and r12.get("deferred") is True)

    # finish 缺 finishedDate → 拒绝（不推算日期）
    r6 = z.finish(task_id="T1", project_key="p", verifier_passed=True,
                  consumed=8, left=0, finished_date=None)
    check("缺 finishedDate → 拒绝", r6["ok"] is False and "不推算" in r6["reason"])

    # finish 门禁未过 → precheck 拒绝
    r7 = z.finish(task_id="T1", project_key="p", verifier_passed=False,
                  consumed=8, left=0, finished_date="2026-11-17")
    check("finish 门禁未过 → precheck 拒绝", r7["ok"] is False and r7.get("stage") == "precheck")

    # finish 缺完成内容/commit → 拒绝（完成任务须带完成内容 + git commit id）
    r9 = z.finish(task_id="T1", project_key="p", verifier_passed=True,
                  consumed=8, left=0, finished_date="2026-11-17")
    check("缺完成内容/commit → 拒绝", r9["ok"] is False and "完成内容" in r9["reason"])

    # finish 成功路径（dry_run）含读回确认语义
    r8 = z.finish(task_id="T1", project_key="p", verifier_passed=True,
                  consumed=8, left=0, finished_date="2026-11-17",
                  summary="完成开发", commit="fd6f11f")
    check("finish 门禁通过 → 执行", r8["ok"] is True)

    # 配置项存在
    from cli_util import load_config
    cfg = load_config()
    zc = cfg.get("zentao", {})
    check("配置含 allow_auto_finish_after_verification",
          "allow_auto_finish_after_verification" in zc)
    check("配置 allow_auto_close=true", zc.get("allow_auto_close") is True)
    check("配置 require_readback=true", zc.get("require_readback") is True)

# --------------------------------------------------------------- 主入口
def main() -> int:
    print("P11 Agent Execution Manager — 集成测试")
    print("=" * 60)
    test_routing()
    test_risk_escalation()
    test_user_override()
    test_task_lock()
    test_agent_lifecycle()
    test_retry()
    test_verifier()
    test_notifier()
    test_jenkins()
    test_state_recovery()
    test_zentao_finish_policy()

    print("\n" + "=" * 60)
    p = sum(1 for _, s, _ in _results if s == PASS)
    f = sum(1 for _, s, _ in _results if s == FAIL)
    print(f"结果: {p} PASS / {f} FAIL / 共 {len(_results)}")
    if f:
        print("\n失败项:")
        for n, s, d in _results:
            if s == FAIL:
                print(f"  ✗ {n} {d}")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
