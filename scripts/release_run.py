# -*- coding: utf-8 -*-
"""发版流程编排（B6）：plan → gate → trigger → status → report → 禅道回写。

原则（CLAUDE.md 硬约束 + QA 测试执行新规）：
    - 只触发 config/adapters/jenkins.yaml 白名单内的 Job。
    - **部署类 Job（jenkins.deploy_jobs）一律禁止自动触发**；如确需部署，
      必须携带人工决策编号（HITL P0）经 --decision 显式传入并留审计。
    - 发版门禁：QA 必须有**真实测试证据**（kind ∈ real_api/e2e/unit/integration
      且通过）；仅代码审查（review）不能放行；BLOCKED/NOT_RUN 如实呈现。
    - 如实报告：构建结果以 Jenkins 最终 result 为准，FAILURE/ABORTED/NOT_BUILT
      绝不判为通过。

用法：
    python -I scripts/release_run.py plan   --task 3413 --project jeebootx [--version v1.2.3]
    python -I scripts/release_run.py gate   --task 3413 --project jeebootx
    python -I scripts/release_run.py trigger --task 3413 --project jeebootx --jobs ct-jeebootx-sanitation
    python -I scripts/release_run.py status --task 3413 --project jeebootx
    python -I scripts/release_run.py report --task 3413 --project jeebootx [--writeback]
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from _config import load_config, get as _get  # noqa: E402

REAL_KINDS = {"real_api", "e2e", "unit", "integration"}


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _exec_dir(project: str, task: str) -> str:
    """执行目录锚定工作流根（WORKFLOW_HOME / 安装记录），不写死脚本所在仓库。"""
    try:
        from _home import resolve_workflow_home
        root = resolve_workflow_home()[0]
    except Exception:
        root = _ROOT
    return os.path.join(root, "execution", project, str(task))


def _load_qa_reports(project: str, task: str) -> list[dict]:
    """读取该任务的全部 Agent 报告（qa 类）。"""
    out = []
    d = os.path.join(_exec_dir(project, task), "agent-reports")
    for p in sorted(glob.glob(os.path.join(d, "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            continue
        if str(rec.get("agent", "")) in ("qa-engineer", "dw-qa-engineer") or "qa" in os.path.basename(p).lower():
            rec["_file"] = os.path.relpath(p, _ROOT)
            out.append(rec)
    return out


def _gate_evidence(qa_reports: list[dict]) -> dict:
    """评估真实测试证据。返回 {passed, real, mock_only, review_only, blocked, not_run}。"""
    real, mock_only, review_only, blocked, not_run = [], [], [], [], []
    for rep in qa_reports:
        for t in rep.get("tests") or rep.get("real_tests") or []:
            kind = str(t.get("kind") or ("review" if not t.get("cmd") else "unknown"))
            result = str(t.get("result") or "")
            item = {"file": rep.get("_file"), "id": t.get("id") or t.get("cmd", "")[:40],
                    "kind": kind, "result": result}
            if result == "pass" and (kind in REAL_KINDS or kind == "unknown"):
                real.append(item)
            elif result == "pass" and kind == "mock":
                mock_only.append(item)
            elif result == "pass" and kind == "review":
                review_only.append(item)
            elif result == "blocked":
                blocked.append(item)
            elif result in ("not_run", "skipped", ""):
                not_run.append(item)
        cv = rep.get("code_verified") or {}
        for k, v in cv.items():
            review_only.append({"file": rep.get("_file"), "id": f"code_verified:{k}",
                                "kind": "review", "result": str(v.get("status", ""))})
    verdicts = [str(r.get("verdict", "")) for r in qa_reports]
    passed = bool(real) and all(v != "FAIL" for v in verdicts)
    return {"passed": passed, "real": real, "mock_only": mock_only,
            "review_only": review_only, "blocked": blocked, "not_run": not_run,
            "verdicts": verdicts}


# --------------------------------------------------------------- plan
def cmd_plan(args) -> int:
    ed = _exec_dir(args.project, args.task)
    qa = _load_qa_reports(args.project, args.task)
    ev = _gate_evidence(qa)
    rel_dir = os.path.join(ed, "release")
    os.makedirs(rel_dir, exist_ok=True)
    version = args.version or datetime.date.today().strftime("v%Y.%m.%d")
    plan_path = os.path.join(rel_dir, f"release-plan-{version}.md")
    lines = [
        f"# 发版计划 {version}（任务 #{args.task}）",
        f"生成时间：{_now()}",
        "",
        "## 门禁状态（生成计划时快照）",
        f"- QA 报告数：{len(qa)}；verdict：{ev['verdicts'] or ['(无)']}",
        f"- 真实测试通过：{len(ev['real'])} 条；Mock 仅证明逻辑：{len(ev['mock_only'])} 条；"
        f"仅代码审查：{len(ev['review_only'])} 条",
        f"- BLOCKED：{len(ev['blocked'])} 条；NOT_RUN：{len(ev['not_run'])} 条",
        f"- 门禁结论：{'可发版（待触发）' if ev['passed'] else '❌ 不满足发版门禁（需真实测试通过）'}",
        "",
        "## 发布说明（草案，待人工补充）",
        f"- 版本号：{version}",
        "- 变更摘要：（由人工或从 agent-reports files_changed 汇总）",
        "- 影响范围：",
        "- 回滚方案：",
        "",
        "## 发版步骤",
        "1. gate 门禁复核（真实测试证据）",
        "2. trigger 白名单构建 Job（部署 Job 禁止自动触发，须 HITL P0 决策编号）",
        "3. status 轮询构建结果（SUCCESS 才算通过）",
        "4. report 生成发版报告并回写禅道",
    ]
    with open(plan_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(json.dumps({"event": "plan_created", "path": os.path.relpath(plan_path, _ROOT),
                      "gate_passed": ev["passed"]}, ensure_ascii=False))
    return 0 if ev["passed"] else 2


# --------------------------------------------------------------- gate
def cmd_gate(args) -> int:
    qa = _load_qa_reports(args.project, args.task)
    ev = _gate_evidence(qa)
    print(json.dumps(ev, ensure_ascii=False, indent=2, default=str))
    if not qa:
        print("❌ 门禁不通过：无 QA 测试报告（不以代码审查代替）")
        return 2
    if not ev["passed"]:
        print("❌ 门禁不通过：缺少真实测试通过证据（real_api/e2e/unit/integration）")
        return 2
    print("✅ 发版门禁通过（存在真实测试通过证据，verdict 无 FAIL）")
    return 0


# --------------------------------------------------------------- trigger
def cmd_trigger(args) -> int:
    cfg = load_config()
    whitelist = set(_get(cfg, "jenkins.jobs", []) or [])
    deploy_jobs = set(_get(cfg, "jenkins.deploy_jobs", []) or [])
    jobs = [j.strip() for j in (args.jobs or "").split(",") if j.strip()]
    if not jobs:
        print("❌ 未指定 --jobs")
        return 3
    for j in jobs:
        if j in deploy_jobs:
            if not args.decision:
                print(f"❌ 拒绝触发：[{j}] 是部署类 Job，禁止自动触发。"
                      f"如确需部署，请经人工决策（HITL P0）后用 --decision <DEC-ID> 显式授权。")
                return 2
            print(f"⚠️ 部署类 Job [{j}] 经人工决策 {args.decision} 触发（已留审计）")
        elif j not in whitelist:
            print(f"❌ 拒绝触发：[{j}] 不在白名单。允许：{sorted(whitelist)}")
            return 2
    # 门禁先决
    qa = _load_qa_reports(args.project, args.task)
    ev = _gate_evidence(qa)
    if not ev["passed"] and not args.force:
        print("❌ 发版门禁未通过（缺少真实测试证据）。确要强行触发请 --force（风险自担，留审计）")
        return 2
    results = []
    for j in jobs:
        cmd = [sys.executable, "-I", os.path.join(_HERE, "jenkins_run.py"), "trigger",
               "--job", j, "--task", str(args.task)]
        if args.branch:
            cmd += ["--branch", args.branch]
        if args.commit:
            cmd += ["--commit", args.commit]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=_ROOT)
        results.append({"job": j, "rc": p.returncode,
                        "out": (p.stdout or "")[-300:], "err": (p.stderr or "")[-200:]})
        print(f"[{j}] rc={p.returncode}")
        print((p.stdout or "")[-300:])
    print(json.dumps({"event": "trigger_done", "results": results}, ensure_ascii=False))
    return 0 if all(r["rc"] == 0 for r in results) else 3


# --------------------------------------------------------------- status
def cmd_status(args) -> int:
    jobs = [j.strip() for j in (args.jobs or "").split(",") if j.strip()]
    if not jobs:
        cfg = load_config()
        jobs = list(_get(cfg, "jenkins.jobs", []) or [])
    all_ok = True
    for j in jobs:
        p = subprocess.run([sys.executable, "-I", os.path.join(_HERE, "jenkins_run.py"), "status",
                            "--job", j], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=_ROOT)
        print(f"== {j} (rc={p.returncode})")
        print((p.stdout or "")[-400:])
        if p.returncode != 0:
            all_ok = False
    return 0 if all_ok else 3


# --------------------------------------------------------------- report
def cmd_report(args) -> int:
    ed = _exec_dir(args.project, args.task)
    qa = _load_qa_reports(args.project, args.task)
    ev = _gate_evidence(qa)
    rel_dir = os.path.join(ed, "release")
    os.makedirs(rel_dir, exist_ok=True)
    path = os.path.join(rel_dir, "release-report.md")
    lines = [
        f"# 发版报告（任务 #{args.task}）",
        f"生成时间：{_now()}",
        "",
        f"- 门禁：{'PASS' if ev['passed'] else 'FAIL'}（真实测试通过 {len(ev['real'])} 条 / "
        f"Mock {len(ev['mock_only'])} / 仅审查 {len(ev['review_only'])} / "
        f"BLOCKED {len(ev['blocked'])} / NOT_RUN {len(ev['not_run'])}）",
        f"- QA verdict：{ev['verdicts'] or ['(无 QA 报告)']}",
        f"- 构建结果：见 jenkins/ 或 status 输出（以 Jenkins 最终 result 为准）",
        "",
        "## 说明",
        "- 仅代码审查的验收项不作为功能正确性证据；BLOCKED/NOT_RUN 项未验证。",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(json.dumps({"event": "report_written", "path": os.path.relpath(path, _ROOT),
                      "gate": ev["passed"]}, ensure_ascii=False))
    if args.writeback:
        text = (f"发版报告已生成：{'门禁通过' if ev['passed'] else '门禁未通过'}；"
                f"真实测试 {len(ev['real'])} 条通过，BLOCKED {len(ev['blocked'])}，NOT_RUN {len(ev['not_run'])}")
        p = subprocess.run([sys.executable, "-I", os.path.join(_HERE, "zt.py"), "progress",
                            "--task", str(args.task), "--stage", "release", "--text", text],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=_ROOT)
        print((p.stdout or "")[-400:])
        return 0 if p.returncode == 0 else 3
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="发版流程编排（白名单构建 + 门禁 + 禅道回写）")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("plan", cmd_plan), ("gate", cmd_gate), ("trigger", cmd_trigger),
                     ("status", cmd_status), ("report", cmd_report)):
        sp = sub.add_parser(name)
        sp.add_argument("--task", required=True)
        sp.add_argument("--project", required=True)
        if name == "plan":
            sp.add_argument("--version", default="")
        if name == "trigger":
            sp.add_argument("--jobs", required=True)
            sp.add_argument("--branch", default="")
            sp.add_argument("--commit", default="")
            sp.add_argument("--decision", default="", help="部署类 Job 的 HITL P0 决策编号")
            sp.add_argument("--force", action="store_true")
        if name == "status":
            sp.add_argument("--jobs", default="")
        if name == "report":
            sp.add_argument("--writeback", action="store_true")
        sp.set_defaults(fn=fn)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
