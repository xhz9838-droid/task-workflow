# -*- coding: utf-8 -*-
"""统一启动预检（Preflight）：一次收集启动所需检查，输出 PASS / WARN / BLOCKED。

复用既有检查器，不新建调度/状态体系：
    - 工作流根           _home.resolve_workflow_home / validate_home
    - 项目配置/上下文    _config.load_config / project_resolver.build_context
    - 仓库校验           repo_check.check_project_repos（只读 Git）
    - 任务参数           _args.parse_invocation（与 Skill 同一解析器）
    - 任务详情           scripts/zt.py detail（只读，可选）

原则：
    - 缺 user_id 只 WARN，不 BLOCKED（普通任务启动不依赖用户身份）
    - 非阻塞检查失败只 WARN，记录后继续
    - 只有影响任务安全/正确执行的问题才 BLOCKED
    - 不触发 Jenkins 构建、部署、业务代码修改

用法：
    python -I scripts/preflight.py jeebootx 3442 3443 3444 3445 [--user <id>] [--json]
    python -I scripts/preflight.py --project jeebootx --tasks 3442,3443 [--fetch-tasks]
退出码：0 = 无 BLOCKED；1 = 存在 BLOCKED；2 = 参数用法错误。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from _args import ArgsError, parse_invocation  # noqa: E402
from _config import ConfigError, load_config  # noqa: E402
from _home import HomeError, resolve_workflow_home, validate_home  # noqa: E402
from project_resolver import build_context, resolve_user_id_optional  # noqa: E402
from repo_check import check_project_repos  # noqa: E402


def _add(checks: list, name: str, status: str, detail="", *, blocking=False, action="") -> None:
    checks.append({
        "name": name,
        "status": status,                      # PASS | WARN | BLOCKED
        "blocking": bool(blocking and status == "BLOCKED"),
        "detail": detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False),
        "action": action,
    })


def fetch_task_detail(task_id: str, home: str) -> dict:
    """只读获取禅道任务详情（复用 scripts/zt.py detail）。"""
    script = os.path.join(home, "scripts", "zt.py")
    if not os.path.isfile(script):
        raise RuntimeError("scripts/zt.py 不存在")
    p = subprocess.run(
        [sys.executable, "-I", script, "detail", "--task", str(task_id)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "zt.py detail 失败").strip()[:300])
    return json.loads(p.stdout or "{}")


def run(project: str = "", tokens=None, user: str = "", *,
        fetch_tasks: bool = False, require_tasks: bool = False, fetcher=None) -> dict:
    """执行预检，返回结构化结果。fetcher 可注入（测试用），默认走 zt.py。"""
    checks: list = []
    actions: list = []

    # ---- 工作流根
    home = ""
    try:
        home, source = resolve_workflow_home()
        problems = validate_home(home)
        if problems:
            _add(checks, "workflow_home", "BLOCKED", problems, blocking=True)
        else:
            _add(checks, "workflow_home", "PASS", "%s（%s）" % (home, source))
    except HomeError as e:
        _add(checks, "workflow_home", "BLOCKED", str(e), blocking=True)

    # ---- 运行依赖
    pyyaml = importlib.util.find_spec("yaml") is not None
    _add(checks, "python_pyyaml", "PASS" if pyyaml else "BLOCKED",
         "PyYAML 可用" if pyyaml else "缺少 PyYAML：pip install pyyaml",
         blocking=not pyyaml, action="" if pyyaml else "安装 PyYAML 后重试")

    # ---- 参数解析（与 Skill 同一解析器）
    ids: list = []
    try:
        raw = ([project] if project else []) + list(tokens or [])
        parsed = parse_invocation(raw)
        project = parsed["project_key"] or project
        ids = parsed["task_ids"]
        if parsed["duplicate_task_ids"]:
            actions.append("任务号去重：%s" % ",".join(parsed["duplicate_task_ids"]))
        _add(checks, "invocation", "PASS", {"project_key": project, "task_ids": ids,
                                            "duplicate_task_ids": parsed["duplicate_task_ids"]})
        if not project or not ids:
            missing = parsed["missing"]
            _add(checks, "invocation_required", "BLOCKED",
                 "缺少 %s；用法：/zentao-dev-workflow {project_key} {task_id} [task_id ...]"
                 % "/".join(missing), blocking=True)
    except ArgsError as e:
        _add(checks, "invocation", "BLOCKED", str(e), blocking=True)
        return _finish(checks, actions, {},
                       {"user_id": "", "user_source": "unresolved"}, ids)

    # ---- 项目配置 + 上下文
    ctx: dict = {}
    user_degraded = False
    if project:
        try:
            ctx = build_context(project)
        except ConfigError as e:
            if getattr(e, "code", "") == "USER_CONFIG_NOT_FOUND" and not user:
                # 自动解析到的用户配置不存在：降级为无用户上下文，不阻塞普通启动
                user_degraded = True
                actions.append("用户配置不存在，已按无用户上下文继续")
                try:
                    ctx = build_context(project, resolve_user=False)
                except Exception as e2:  # noqa: BLE001
                    _add(checks, "project_context", "BLOCKED", "%s: %s" % (type(e2).__name__, e2),
                         blocking=True)
            else:
                _add(checks, "project_context", "BLOCKED", "%s: %s" % (type(e).__name__, e),
                     blocking=True)
        except Exception as e:  # noqa: BLE001
            _add(checks, "project_context", "BLOCKED", "%s: %s" % (type(e).__name__, e),
                 blocking=True)
        if ctx:
            _add(checks, "project_config", "PASS", {
                "project_key": ctx.get("project_key"), "name": ctx.get("project_name"),
                "execution_root": ctx.get("execution_root"),
                "agents": ctx.get("agents", []),
            })
            enabled_agents = ctx.get("agents") or []
            if enabled_agents and home:
                missing = [a for a in enabled_agents if not any(os.path.exists(f) for f in (
                    os.path.join(home, ".claude", "agents", a + ".md"),
                    os.path.join(home, "agents", a + ".md"),
                    os.path.join(home, "skill", "agents", a + ".md"),
                ))]
                _add(checks, "agent_defs", "WARN" if missing else "PASS",
                     missing or sorted(enabled_agents),
                     action="补充 Agent 定义后重试" if missing else "")

    # ---- 用户身份（可选）
    uid, user_source = resolve_user_id_optional(user or None)
    if uid and not user_degraded:
        _add(checks, "user", "PASS", "%s（%s）" % (uid, user_source))
    elif uid:
        _add(checks, "user", "WARN",
             "%s（%s）：用户配置不存在，已按无用户上下文继续" % (uid, user_source),
             action="补充 config/users/%s.yaml 以启用用户级仓库路径映射" % uid)
    else:
        _add(checks, "user", "WARN", "未解析 user_id：%s" % user_source,
             action="普通任务可继续；用户级仓库映射与 Human Decision 决策人校验不受影响")

    # ---- 仓库校验（只读）
    if ctx:
        try:
            cfg = load_config(project, uid or None, strict=False)
            results = check_project_repos(cfg.get("project") or {}, ctx.get("repo_paths") or {})
            for r in results:
                detail = {"repo": r.repo_key, "path": r.path, "technology": r.technology,
                          "problems": r.problems}
                if r.status == "ok" and r.details.get("dirty"):
                    _add(checks, "repo:%s" % r.repo_key, "WARN", detail,
                         action="工作区有未提交改动（不阻断，不自动清理）")
                elif not r.path:
                    # 无本地路径：有可用 user 映射时属配置缺失，无 user/降级时属可降级
                    status = "BLOCKED" if uid and not user_degraded else "WARN"
                    _add(checks, "repo:%s" % r.repo_key, status, detail,
                         blocking=status == "BLOCKED",
                         action="补充 config/users/*.yaml project_paths 或项目 repositories[].path")
                elif r.status == "ok":
                    _add(checks, "repo:%s" % r.repo_key, "PASS", detail)
                elif r.status == "mismatch":
                    _add(checks, "repo:%s" % r.repo_key, "BLOCKED", detail, blocking=True,
                         action="核对仓库路径/remote/角色，不自动修复")
                else:  # blocked
                    _add(checks, "repo:%s" % r.repo_key, "BLOCKED", detail, blocking=True,
                         action="修复仓库路径或 Git 环境后重试")
        except Exception as e:  # noqa: BLE001
            _add(checks, "repo_check", "WARN", "%s: %s" % (type(e).__name__, e),
                 action="仓库校验失败不阻塞启动，进入开发前需复核")

    # ---- 任务执行目录 / 开发计划 / 任务详情
    if ctx and ids:
        exec_root = ctx.get("execution_root") or ""
        for tid in ids:
            task_dir = os.path.join(exec_root, tid)
            has_dag = os.path.isfile(os.path.join(task_dir, "tasks.yaml"))
            has_ctx = os.path.isfile(os.path.join(task_dir, "task-context.md"))
            if has_dag:
                _add(checks, "task:%s" % tid, "PASS", {"exec_dir": task_dir, "dag": True,
                                                       "task_context": has_ctx})
            else:
                _add(checks, "task:%s" % tid, "WARN",
                     {"exec_dir": task_dir, "dag": False, "task_context": has_ctx},
                     action="首次执行：进入需求分析后生成 tasks.yaml")
        if fetch_tasks:
            fn = fetcher or (lambda t: fetch_task_detail(t, home))
            for tid in ids:
                try:
                    detail = fn(tid)
                    _add(checks, "task_detail:%s" % tid, "PASS", {
                        "id": detail.get("id"), "name": detail.get("name"),
                        "status": detail.get("status"), "assigned_to": detail.get("assignedTo"),
                    })
                except Exception as e:  # noqa: BLE001
                    _add(checks, "task_detail:%s" % tid,
                         "BLOCKED" if require_tasks else "WARN", str(e)[:300],
                         blocking=require_tasks, action="检查禅道连接/任务号后重试")

    # ---- 运行环境（非阻塞）
    if home:
        db = os.path.join(home, "agent-manager", "logs", "agent_manager.db")
        _add(checks, "state_db", "PASS" if os.path.isfile(db) else "WARN",
             db if os.path.isfile(db) else "状态库不存在（首次运行会创建）")
        zs = os.path.expanduser(os.environ.get("ZENTAO_SKILL_DIR", "~/.claude/skills"))
        has_zt = os.path.isdir(os.path.join(zs, "zentao"))
        _add(checks, "zentao_skill", "PASS" if has_zt else "WARN",
             "%s/zentao" % zs, action="" if has_zt else "禅道集成不可用，可无 ZenTao 运行")
        mcp_user = False
        try:
            with open(os.path.expanduser("~/.claude.json"), encoding="utf-8") as f:
                mcp_user = "human-decision" in ((json.load(f) or {}).get("mcpServers") or {})
        except Exception:
            pass
        _add(checks, "hitl_mcp", "PASS" if mcp_user else "WARN",
             "human-decision MCP user scope",
             action="" if mcp_user else "L3 决策在业务项目目录可能不可用")

    return _finish(checks, actions, ctx, {"user_id": uid, "user_source": user_source}, ids)


def _finish(checks, actions, ctx, user, ids) -> dict:
    blocked = [c for c in checks if c["status"] == "BLOCKED"]
    summary = {"pass": sum(c["status"] == "PASS" for c in checks),
               "warn": sum(c["status"] == "WARN" for c in checks),
               "blocked": len(blocked)}
    return {
        "ok": not blocked,
        "checks": checks,
        "summary": summary,
        "actions": actions,
        "task_ids": ids,
        "user": user,
        "context": ctx,
    }


def _print_text(r: dict) -> None:
    print("zentao-dev-workflow preflight")
    print("  任务      : %s" % (", ".join(r.get("task_ids") or []) or "(无)"))
    print("  用户      : %s" % (r.get("user", {}).get("user_id") or "(未解析)"))
    for c in r["checks"]:
        print("  [%s] %s: %s" % (c["status"], c["name"], c["detail"]))
        if c.get("action"):
            print("        → %s" % c["action"])
    for a in r.get("actions", []):
        print("  ↳ %s" % a)
    s = r["summary"]
    print("结论: %s（PASS=%d WARN=%d BLOCKED=%d）"
          % ("可继续" if r["ok"] else "存在阻塞项", s["pass"], s["warn"], s["blocked"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="preflight.py", description="工作流统一启动预检")
    ap.add_argument("tokens", nargs="*", help="project_key 与任务号（也支持 --project/--tasks）")
    ap.add_argument("--project", default="")
    ap.add_argument("--tasks", default="", help="逗号分隔任务号，如 3442,3443")
    ap.add_argument("--user", default="", help="工作流 user_id（可选）")
    ap.add_argument("--fetch-tasks", action="store_true", help="只读获取禅道任务详情")
    ap.add_argument("--require-tasks", action="store_true",
                    help="任务详情获取失败视为 BLOCKED（默认 WARN）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="", help="把结果写入 JSON 文件（供后续阶段复用）")
    args = ap.parse_args(argv)

    tokens = list(args.tokens)
    if args.tasks:
        tokens += ["--tasks", args.tasks]
    r = run(args.project, tokens, args.user,
            fetch_tasks=args.fetch_tasks, require_tasks=args.require_tasks)

    if args.out:
        out_dir = os.path.dirname(os.path.abspath(args.out))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2, default=str)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        _print_text(r)

    if not r["task_ids"] and any(c["name"] == "invocation" and c["status"] == "BLOCKED"
                                 for c in r["checks"]):
        return 2
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
