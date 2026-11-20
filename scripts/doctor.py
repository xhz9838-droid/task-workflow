# -*- coding: utf-8 -*-
"""运行诊断（doctor）：版本 / 工作流根 / 配置 / 依赖 / 状态库 / Skill 安装。

用法：
    python -I scripts/doctor.py [--project <key>] [--user <id>] [--json]

输出不包含任何凭据值（只报告键是否存在）。
退出码：0 = 无关键问题；1 = 存在关键问题（配置/依赖/目录）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_REPO, "agent-manager")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _version() -> str:
    try:
        with open(os.path.join(_REPO, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "unknown"


def _adapter_files(root: str) -> dict:
    d = os.path.join(root, "config", "adapters")
    out = {}
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if fn.endswith((".yaml", ".yml", ".json")) and ".example" not in fn:
                out[os.path.splitext(fn)[0]] = True
    return out


def collect(project: str = "", user: str = "") -> dict:
    report = {"ok": True, "problems": [], "warnings": [], "info": {}}

    def problem(code, detail):
        report["ok"] = False
        report["problems"].append({"code": code, "detail": detail})

    def warn(code, detail):
        report["warnings"].append({"code": code, "detail": detail})

    report["info"]["version"] = _version()
    report["info"]["python"] = sys.version.split()[0]
    report["info"]["cwd"] = os.getcwd()

    # 工作流根
    try:
        from _home import resolve_workflow_home, validate_home
        home, source = resolve_workflow_home()
        report["info"]["workflow_home"] = home
        report["info"]["home_source"] = source
        probs = validate_home(home)
        if probs:
            problem("HOME_INVALID", probs)
    except Exception as e:
        home = ""
        problem("HOME_NOT_FOUND", str(e))

    # 依赖
    has_yaml = importlib.util.find_spec("yaml") is not None
    report["info"]["pyyaml"] = has_yaml
    if not has_yaml:
        problem("DEP_MISSING", "缺少 PyYAML：pip install pyyaml")

    if home:
        # .env 键（只报键名，不报值）
        env_path = os.path.join(home, ".env")
        keys = []
        if os.path.isfile(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        keys.append(line.split("=", 1)[0].strip())
        report["info"]["env_present"] = os.path.isfile(env_path)
        report["info"]["env_keys"] = sorted(keys)
        report["info"]["adapters"] = _adapter_files(home)
        # 外部禅道 Skill
        zs = os.path.expanduser(os.environ.get("ZENTAO_SKILL_DIR", "~/.claude/skills"))
        report["info"]["zentao_skill"] = os.path.isdir(os.path.join(zs, "zentao"))
        if not report["info"]["zentao_skill"]:
            warn("ZENTAO_SKILL_MISSING", "未找到 %s/zentao（禅道集成不可用）" % zs)
        # SQLite 状态库
        db = os.path.join(home, "agent-manager", "logs", "agent_manager.db")
        report["info"]["db"] = db
        if os.path.isfile(db):
            try:
                c = sqlite3.connect(db)
                report["info"]["db_schema"] = c.execute("PRAGMA user_version").fetchone()[0]
                report["info"]["db_executions"] = c.execute(
                    "SELECT COUNT(*) FROM execution_runs").fetchone()[0]
                report["info"]["db_nodes"] = c.execute(
                    "SELECT COUNT(*) FROM node_dispatches").fetchone()[0]
                c.close()
            except Exception as e:
                problem("DB_UNREADABLE", str(e))
        else:
            warn("DB_MISSING", "状态库不存在（首次运行会创建）")

    # 安装记录 / Skill
    record = os.path.expanduser("~/.claude/zentao-dev-workflow.home")
    report["info"]["install_record"] = record if os.path.isfile(record) else None
    skill = os.path.expanduser("~/.claude/skills/zentao-dev-workflow/SKILL.md")
    report["info"]["skill_installed"] = os.path.isfile(skill)
    if not report["info"]["skill_installed"]:
        warn("SKILL_NOT_INSTALLED", "未安装到 ~/.claude/skills/zentao-dev-workflow")

    # HITL MCP（user scope）——L3 决策工具在任意项目目录可用
    mcp_user = False
    try:
        with open(os.path.expanduser("~/.claude.json"), encoding="utf-8") as f:
            mcp_user = "human-decision" in ((json.load(f) or {}).get("mcpServers") or {})
    except Exception:
        pass
    report["info"]["mcp_human_decision_user"] = mcp_user
    if not mcp_user:
        warn("HITL_MCP_NOT_REGISTERED",
             "human-decision MCP 未注册到 user scope（L3 决策在业务项目目录可能不可用）")

    # 配置 + 身份
    if project:
        try:
            from _config import load_config
            cfg = load_config(project, user or None, strict=True)
            report["info"]["project"] = project
            report["info"]["project_agents"] = sorted(
                k for k, v in (cfg.get("project", {}).get("agents", {}) or {}).items() if v is True)
        except Exception as e:
            problem(getattr(e, "code", "CONFIG_ERROR"), str(e))
    try:
        from project_resolver import _resolve_user_id
        uid, src = _resolve_user_id(user or None)
        report["info"]["user_id"] = uid
        report["info"]["user_source"] = src
    except Exception as e:
        uid = ""
        report["info"]["user_id"] = None
        warn("USER_NOT_RESOLVED", str(e))

    return report


def _print_human(r: dict) -> None:
    i = r["info"]
    print("zentao-dev-workflow doctor")
    print("  版本        : %s" % i.get("version"))
    print("  工作流根    : %s" % i.get("workflow_home", "?"))
    print("  来源        : %s" % i.get("home_source", "?"))
    print("  Python      : %s   PyYAML=%s" % (i.get("python"), i.get("pyyaml")))
    print("  项目        : %s" % (i.get("project") or "(未指定)"))
    print("  用户        : %s (%s)" % (i.get("user_id"), i.get("user_source")))
    print("  适配器      : %s" % (", ".join(sorted(i.get("adapters", {}))) or "(无)"))
    print("  .env        : %s  键=%s" % (i.get("env_present"), ",".join(i.get("env_keys", []))))
    if "db_schema" in i:
        print("  SQLite      : schema v%s, executions=%s, nodes=%s"
              % (i.get("db_schema"), i.get("db_executions"), i.get("db_nodes")))
    print("  Skill 安装  : %s   禅道Skill=%s"
          % (i.get("skill_installed"), i.get("zentao_skill")))
    for w in r["warnings"]:
        print("  ⚠ %s: %s" % (w["code"], w["detail"]))
    for p in r["problems"]:
        print("  ❌ %s: %s" % (p["code"], p["detail"]))
    print("结论: %s" % ("OK" if r["ok"] else "存在问题（见上）"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="doctor.py", description="工作流运行诊断")
    ap.add_argument("--project", default="")
    ap.add_argument("--user", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = collect(args.project, args.user)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        _print_human(r)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
