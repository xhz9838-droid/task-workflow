# -*- coding: utf-8 -*-
"""统一安装/升级/迁移状态与跨目录迁移（不引入第三方依赖）。

命令：
    python -I scripts/install_manager.py status --root <repo> --user-claude <dir> [--json]
    python -I scripts/install_manager.py detect --root <repo> --user-claude <dir> [--json]
    python -I scripts/install_manager.py sync-mcp --root <repo> --user-claude <dir>
    python -I scripts/install_manager.py migrate --root <new> --user-claude <dir> [--python python]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

AGENTS = ("dw-architect", "dw-database", "dw-java-backend", "dw-web-frontend",
          "dw-mobile-app", "dw-qa-engineer", "dw-integration-reviewer")
MCP_NAME = "human-decision"
ROUTER_REL = os.path.join("agent-manager", "human_decision", "prompt_router.py")
MCP_REL = os.path.join("agent-manager", "human_decision", "mcp_server.py")
DEFAULT_BASE = os.path.join("~", ".workflow")


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _hash(path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except OSError:
        return ""


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _backup(path: str) -> str:
    if not os.path.exists(path):
        return ""
    bak = "%s.bak.install.%s" % (path, datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
    shutil.copy2(path, bak)
    return bak


def paths(root: str, user_claude: str) -> dict:
    parent = os.path.dirname(os.path.abspath(user_claude))
    return {
        "root": os.path.abspath(root),
        "user_claude": os.path.abspath(user_claude),
        "home": os.path.join(user_claude, "zentao-dev-workflow.home"),
        "user_json": os.path.join(user_claude, "zentao-dev-workflow.json"),
        "settings": os.path.join(user_claude, "settings.json"),
        "claude_json": os.path.join(parent, ".claude.json"),
        "skill_src": _skill_src(root),
        "agents_src": _agents_src(root),
        "installed_skill": os.path.join(user_claude, "skills", "zentao-dev-workflow"),
        "installed_agents": os.path.join(user_claude, "agents"),
    }


def _skill_src(root: str) -> str:
    p = os.path.join(root, "skill")
    if os.path.isdir(p):
        return p
    return os.path.join(root, ".claude", "skills", "zentao-dev-workflow")


def _agents_src(root: str) -> str:
    p = os.path.join(root, "agents")
    if os.path.isdir(p):
        return p
    return os.path.join(root, ".claude", "agents")


def _mcp_entry(claude_json: str) -> dict:
    data = _read_json(claude_json) or {}
    return (data.get("mcpServers") or {}).get(MCP_NAME) or {}


def _mcp_path(entry: dict) -> str:
    for a in (entry.get("args") or []):
        if str(a).endswith("mcp_server.py"):
            return str(a)
    return ""


def _hook_root(settings: str) -> str:
    data = _read_json(settings) or {}
    for e in ((data.get("hooks") or {}).get("UserPromptSubmit") or []):
        for h in (e.get("hooks") or []):
            cmd = str(h.get("command") or "")
            norm = cmd.replace("\\", "/")
            if "/agent-manager/human_decision/prompt_router.py" not in norm:
                continue
            m = re.search(r'"([A-Za-z]:/[^"]+?)/agent-manager/human_decision/prompt_router\.py"', norm)
            if m:
                return m.group(1)
            prefix = norm.split("/agent-manager/human_decision/prompt_router.py", 1)[0]
            return prefix.rsplit(" ", 1)[-1].strip('" ')
    return ""


def detect(root: str, user_claude: str) -> dict:
    p = paths(root, user_claude)
    root_n = os.path.abspath(root)
    cands = {}
    for label, path, key in (
        (".home", p["home"], "text"),
        ("user_json", p["user_json"], "workflow_home"),
        ("hook", p["settings"], "hook"),
        ("mcp", p["claude_json"], "mcp"),
    ):
        if key == "text":
            try:
                val = open(path, encoding="utf-8").read().strip()
            except OSError:
                val = ""
        elif key == "workflow_home":
            val = str((_read_json(path) or {}).get("workflow_home") or "")
        elif key == "hook":
            val = _hook_root(path)
        else:
            val = _mcp_path(_mcp_entry(path))
        if val:
            v = os.path.abspath(val)
            if os.path.isdir(v) and v != root_n:
                cands.setdefault(v, []).append(label)
    return {"new_root": root_n, "old_roots": cands}


def status(root: str, user_claude: str) -> dict:
    p = paths(root, user_claude)
    root_n = os.path.abspath(root)
    checks = {}

    def add(name, ok, detail="", fix=""):
        checks[name] = {"status": "OK" if ok else "FAIL", "detail": detail, "fix": fix}

    add("runtime", all(os.path.exists(os.path.join(root_n, x)) for x in
                       ("config/workflow.yaml", "scripts/_config.py")),
        root_n, "检查发行版/运行时目录是否完整")

    home = ""
    try:
        home = open(p["home"], encoding="utf-8").read().strip() if os.path.exists(p["home"]) else ""
    except OSError:
        pass
    add("home", bool(home) and os.path.abspath(home) == root_n, home or "(缺失)",
        "重新运行 scripts/install.sh")

    uj = _read_json(p["user_json"]) or {}
    uj_home = str(uj.get("workflow_home") or "")
    add("user_json", not uj_home or os.path.abspath(uj_home) == root_n,
        uj_home or "(未配置)", "跨目录请运行 scripts/install.sh --migrate")

    hook_cmd = _hook_root(p["settings"])
    hook_ok = bool(hook_cmd) and os.path.abspath(hook_cmd) == root_n
    add("hook", hook_ok, hook_cmd or "(未注册)",
        "重新运行 scripts/install.sh（或 --with-mcp）")

    entry = _mcp_entry(p["claude_json"])
    mcp_path = _mcp_path(entry)
    mcp_expected = os.path.join(root_n, MCP_REL)
    add("mcp", (not entry) or (os.path.abspath(mcp_path) == os.path.abspath(mcp_expected)),
        mcp_path or "(未注册)", "scripts/install.sh --with-mcp 或 --migrate")

    skill_ok = os.path.isfile(os.path.join(p["installed_skill"], "SKILL.md"))
    skill_same = skill_ok and _hash(os.path.join(p["installed_skill"], "SKILL.md")) == _hash(
        os.path.join(p["skill_src"], "SKILL.md"))
    add("skill", skill_same, p["installed_skill"], "重新运行 scripts/install.sh")

    agents_ok = all(os.path.isfile(os.path.join(p["installed_agents"], a + ".md")) for a in AGENTS)
    agents_same = agents_ok and all(
        _hash(os.path.join(p["installed_agents"], a + ".md")) == _hash(
            os.path.join(p["agents_src"], a + ".md")) for a in AGENTS)
    add("agents", agents_same, p["installed_agents"], "重新运行 scripts/install.sh")

    deps = all(importlib.util.find_spec(m) is not None for m in ("yaml", "mcp"))
    add("dependencies", deps, "PyYAML/mcp", "pip install -r requirements.txt")

    data = {
        "config": os.path.isfile(os.path.join(root_n, "config", "workflow.yaml")),
        "env": os.path.isfile(os.path.join(root_n, ".env")) or
               os.path.isfile(os.path.join(root_n, "config", ".env")),
        "execution": os.path.isdir(os.path.join(root_n, "execution")),
        "db": os.path.isfile(os.path.join(root_n, "agent-manager", "logs", "agent_manager.db")),
    }
    add("runtime_data", True, data, "")

    installed = all(checks[k]["status"] == "OK" for k in ("skill", "agents", "hook"))
    mismatch = [k for k in ("home", "user_json", "hook", "mcp") if checks[k]["status"] != "OK"]
    # update_available：已安装但安装副本与运行时源不一致
    update_available = installed and (not skill_same or not agents_same)
    if not installed and not any(checks[k]["status"] == "OK" for k in ("skill", "agents")):
        overall = "NOT_INSTALLED"
    elif not deps or not checks["runtime"]["status"] == "OK":
        overall = "DEGRADED"
    elif mismatch:
        if checks["home"]["status"] != "OK":
            overall = "PATH_MISMATCH"
        elif checks["user_json"]["status"] != "OK":
            overall = "CONFIG_INCONSISTENT"
        elif checks["hook"]["status"] != "OK":
            overall = "HOOK_MISMATCH"
        else:
            overall = "MCP_MISMATCH"
    elif update_available:
        overall = "UPDATE_AVAILABLE"
    else:
        overall = "INSTALLED" if installed else "DEGRADED"
    return {"overall": overall, "root": root_n, "checks": checks,
            "ready": overall in ("INSTALLED", "UPDATE_AVAILABLE"),
            "old_roots": detect(root, user_claude)["old_roots"]}


def _copy_missing(src: str, dst: str) -> None:
    if os.path.isdir(src):
        os.makedirs(dst, exist_ok=True)
        for name in os.listdir(src):
            if name in ("__pycache__", ".pytest_cache"):
                continue
            _copy_missing(os.path.join(src, name), os.path.join(dst, name))
    else:
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
            shutil.copy2(src, dst)


def _copy_db(src: str, dst: str) -> None:
    if os.path.exists(dst):
        return
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    s = sqlite3.connect(src)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        s.close()
        d.close()


# ----------------------------------------------------- 默认目录（~/.workflow）
def _is_link(path: str) -> bool:
    if os.path.islink(path):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction and isjunction(path))


def _link_dir(target: str, link: str) -> bool:
    """runtime/config、runtime/execution、runtime/agent-manager/logs → 用户数据目录。"""
    target = os.path.abspath(target)
    link = os.path.abspath(link)
    if os.path.exists(link):
        if _is_link(link) and os.path.realpath(link) == os.path.realpath(target):
            return True
        return False
    os.makedirs(os.path.dirname(link), exist_ok=True)
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        pass
    if os.name != "nt":
        return False
    try:
        p = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                           capture_output=True, text=True, timeout=30)
        return p.returncode == 0 and os.path.exists(link)
    except (OSError, subprocess.SubprocessError):
        return False


def _link_env(config_dir: str, runtime: str) -> None:
    """config/.env 为真实文件；runtime/.env 用同卷硬链接（失败则复制）。"""
    env = os.path.join(config_dir, ".env")
    rt = os.path.join(runtime, ".env")
    if not os.path.isfile(env) or os.path.exists(rt):
        return
    try:
        os.link(env, rt)
    except OSError:
        shutil.copy2(env, rt)


_RUNTIME_EXCLUDES = {
    ".git", ".github", ".env", "config", "execution", "logs", "data", "backups",
    "tests", "docs", "reports", "__pycache__", ".pytest_cache", ".workflow", "runtime",
}


def _copy_runtime(source: str, runtime: str) -> None:
    """复制程序文件；配置/数据/日志目录由软链指向用户目录。"""
    source = os.path.abspath(source)

    def _ignore(dirpath, names):
        out = set()
        base = os.path.basename(dirpath).lower()
        for name in names:
            if name.lower() in _RUNTIME_EXCLUDES or name.lower().endswith(".pyc"):
                out.add(name)
        if base == "logs":
            out.update(names)
        return out

    shutil.copytree(source, runtime, dirs_exist_ok=True, ignore=_ignore)


def _copy_logs(old_logs: str, new_logs: str) -> None:
    if not os.path.isdir(old_logs):
        return
    os.makedirs(new_logs, exist_ok=True)
    for name in os.listdir(old_logs):
        if name == "agent_manager.db":
            continue
        src = os.path.join(old_logs, name)
        dst = os.path.join(new_logs, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)


def install_default(source: str, user_claude: str, base: str = "",
                    python_bin: str = "python", with_mcp: bool = False) -> dict:
    """把发行版复制到 ~/.workflow/runtime，并与 config/data/logs 分离。"""
    source = os.path.abspath(source)
    base = os.path.abspath(os.path.expanduser(base or DEFAULT_BASE))
    runtime = os.path.join(base, "runtime")
    config = os.path.join(base, "config")
    data = os.path.join(base, "data")
    logs = os.path.join(base, "logs")
    backups = os.path.join(base, "backups")

    for rel in ("config/workflow.yaml", "scripts/_config.py", "skill/SKILL.md"):
        if not os.path.exists(os.path.join(source, rel)):
            raise ValueError("NOT_A_DISTRIBUTION：缺少 %s" % rel)

    det = detect(runtime, user_claude)
    old_roots = det["old_roots"]
    if len(old_roots) > 1:
        raise ValueError("MULTIPLE_OLD_ROOTS " + json.dumps(old_roots, ensure_ascii=False))
    old = next(iter(old_roots), "")

    for d in (base, config, data, os.path.join(data, "execution"), logs, backups):
        os.makedirs(d, exist_ok=True)
    if old and os.path.abspath(old) not in (runtime, base):
        _copy_missing(os.path.join(old, "config"), config)
        old_env = os.path.join(old, ".env")
        if os.path.isfile(old_env) and not os.path.isfile(os.path.join(config, ".env")):
            shutil.copy2(old_env, os.path.join(config, ".env"))
        _copy_missing(os.path.join(old, "execution"), os.path.join(data, "execution"))
        _copy_logs(os.path.join(old, "agent-manager", "logs"), logs)
        _copy_db(os.path.join(old, "agent-manager", "logs", "agent_manager.db"),
                 os.path.join(logs, "agent_manager.db"))

    if os.path.normcase(os.path.abspath(source)) != os.path.normcase(runtime):
        _copy_missing(os.path.join(source, "config"), config)
        _copy_runtime(source, runtime)
    for target, link in ((config, os.path.join(runtime, "config")),
                         (os.path.join(data, "execution"), os.path.join(runtime, "execution")),
                         (logs, os.path.join(runtime, "agent-manager", "logs"))):
        if not _link_dir(target, link):
            raise ValueError("LINK_FAILED：%s → %s（目录已存在且不是本安装创建的链接）" % (link, target))
    _link_env(config, runtime)

    env = dict(os.environ, WORKFLOW_USER_CLAUDE=user_claude, PYTHON_BIN=python_bin,
               WORKFLOW_ALLOW_CROSS_ROOT="1")
    cmd = ["bash", os.path.join(runtime, "scripts", "install.sh")]
    if with_mcp:
        cmd.append("--with-mcp")
    p = None
    for attempt in (1, 2):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=env, timeout=180)
            break
        except subprocess.TimeoutExpired:
            if attempt == 2:
                raise
    if p.returncode != 0:
        raise ValueError("INSTALL_FAILED：%s\n%s" % (p.stdout.strip(), p.stderr.strip()))
    # 用户级 JSON 优先于 .home，必须与 runtime 同步
    up = paths(runtime, user_claude)["user_json"]
    if old or os.path.isfile(up):
        _backup(up)
        uj = _read_json(up) or {}
        uj["workflow_home"] = runtime
        _write_json(up, uj)
    # 旧 MCP 已注册但未显式 --with-mcp：仍要跟随新根，否则留下旧路径
    if not with_mcp and _mcp_path(_mcp_entry(paths(runtime, user_claude)["claude_json"])):
        sync_mcp(runtime, user_claude)

    version = ""
    try:
        with open(os.path.join(runtime, "VERSION"), encoding="utf-8") as f:
            version = f.read().strip()
    except OSError:
        pass
    manifest = {
        "schema": 1,
        "installed_at": _now(),
        "version": version,
        "source": source,
        "home": base,
        "runtime": runtime,
        "config": config,
        "data": data,
        "logs": logs,
        "backups": backups,
        "python": python_bin,
        "mcp": bool(with_mcp),
    }
    _write_json(os.path.join(base, "install.json"), manifest)
    st = status(runtime, user_claude)
    return {"manifest": manifest, "status": st["overall"], "ready": st.get("ready", False),
            "old_root": old, "installer": p.stdout.strip()}



def sync_mcp(root: str, user_claude: str) -> dict:
    p = paths(root, user_claude)
    cj = p["claude_json"]
    data = _read_json(cj)
    if data is None and os.path.exists(cj):
        raise ValueError("无法解析 %s" % cj)
    data = data or {}
    servers = data.setdefault("mcpServers", {})
    expected = os.path.join(os.path.abspath(root), MCP_REL)
    cur = servers.get(MCP_NAME) or {}
    if _mcp_path(cur) and os.path.abspath(_mcp_path(cur)) == os.path.abspath(expected):
        return {"changed": False, "path": expected}
    _backup(cj)
    servers[MCP_NAME] = {"command": "python", "args": ["-I", expected], "env": {}}
    _write_json(cj, data)
    return {"changed": True, "path": expected}


def migrate(root: str, user_claude: str, python_bin: str) -> dict:
    p = paths(root, user_claude)
    new = os.path.abspath(root)
    det = detect(root, user_claude)
    old_roots = det["old_roots"]
    if not old_roots:
        raise ValueError("未发现可迁移的旧运行时根（.home / user_json / hook / MCP 均未指向其他有效目录）")
    if len(old_roots) > 1:
        raise ValueError("MULTIPLE_OLD_ROOTS " + json.dumps(old_roots, ensure_ascii=False))
    old = next(iter(old_roots))
    actions = []
    backups = {}
    for key in ("home", "user_json", "settings", "claude_json"):
        bak = _backup(p[key])
        if bak:
            backups[key] = bak
    try:
        # 数据：只补新目录缺失项，不覆盖新目录已有数据
        for rel in ("config", ".env", "execution"):
            src = os.path.join(old, rel)
            dst = os.path.join(new, rel)
            if os.path.exists(src) and not os.path.exists(dst):
                _copy_missing(src, dst)
                actions.append("copied:" + rel)
            elif os.path.exists(src):
                _copy_missing(src, dst)
                actions.append("merged:" + rel)
        db_src = os.path.join(old, "agent-manager", "logs", "agent_manager.db")
        db_dst = os.path.join(new, "agent-manager", "logs", "agent_manager.db")
        if os.path.exists(db_src):
            _copy_db(db_src, db_dst)
            actions.append("sqlite_backup")
        # 用户级 JSON / .home
        uj = _read_json(p["user_json"]) or {}
        uj["workflow_home"] = new
        _write_json(p["user_json"], uj)
        os.makedirs(os.path.dirname(p["home"]), exist_ok=True)
        with open(p["home"], "w", encoding="utf-8") as f:
            f.write(new + "\n")
        # Hook
        import hitl_hook
        router = os.path.join(new, ROUTER_REL).replace("\\", "/")
        cmd = '%s -I "%s"' % (python_bin, router)
        hr = hitl_hook.install(p["settings"], cmd, new)
        actions.append("hook")
        # MCP
        mr = sync_mcp(new, user_claude)
        actions.append("mcp")
        st = status(new, user_claude)
        log = {"ts": _now(), "old_root": old, "new_root": new, "actions": actions,
               "hook": hr, "mcp": mr, "status": st["overall"]}
        _write_json(os.path.join(user_claude, "zentao-dev-workflow.migrate.json"), log)
        return log
    except Exception:
        for key, bak in backups.items():
            try:
                shutil.copy2(bak, p[key])
            except OSError:
                pass
        raise


def _print_status(st: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return
    print("Workflow Installation Check\n")
    for name, c in st["checks"].items():
        print("%s:\n  Status: %s\n  Path: %s" % (name, c["status"], c["detail"]))
        if c["fix"] and c["status"] != "OK":
            print("  Fix: %s" % c["fix"])
        print()
    print("Overall:\n  %s%s" % (st["overall"], " (READY)" if st.get("ready") else ""))
    if st.get("old_roots"):
        print("\nOld runtime roots:\n  " + json.dumps(st["old_roots"], ensure_ascii=False))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="install_manager.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("status", "detect", "sync-mcp", "migrate"):
        sp = sub.add_parser(name)
        sp.add_argument("--root", required=True)
        sp.add_argument("--user-claude", required=True)
        sp.add_argument("--json", action="store_true")
        if name == "migrate":
            sp.add_argument("--python", default="python")
    sp = sub.add_parser("install-default")
    sp.add_argument("--source", required=True)
    sp.add_argument("--user-claude", required=True)
    sp.add_argument("--dir", default="", help="安装根（默认 ~/.workflow）")
    sp.add_argument("--python", default="python")
    sp.add_argument("--with-mcp", action="store_true")
    sp.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "status":
            st = status(args.root, args.user_claude)
            _print_status(st, args.json)
            return 0 if st["overall"] in ("INSTALLED", "UPDATE_AVAILABLE", "NOT_INSTALLED") else 1
        if args.cmd == "detect":
            det = detect(args.root, args.user_claude)
            print(json.dumps(det, ensure_ascii=False, indent=2))
            return 1 if det.get("old_roots") else 0
        if args.cmd == "sync-mcp":
            print(json.dumps(sync_mcp(args.root, args.user_claude), ensure_ascii=False))
            return 0
        if args.cmd == "install-default":
            log = install_default(args.source, args.user_claude, args.dir,
                                  args.python, args.with_mcp)
            print(json.dumps(log, ensure_ascii=False, indent=2))
            return 0 if log.get("ready") else 1
        log = migrate(args.root, args.user_claude, args.python)
        print(json.dumps(log, ensure_ascii=False, indent=2))
        return 0 if log.get("status") in ("INSTALLED", "UPDATE_AVAILABLE") else 1
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": "%s: %s" % (type(e).__name__, e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
