# -*- coding: utf-8 -*-
"""HITL daemon/supervisor 生命周期 CLI（跨平台，无额外依赖）。

用法：
    python agent-manager/human_decision/lifecycle.py status [--json]
    python agent-manager/human_decision/lifecycle.py start
    python agent-manager/human_decision/lifecycle.py stop
    python agent-manager/human_decision/lifecycle.py restart
    python agent-manager/human_decision/lifecycle.py recover
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)  # agent-manager/
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from human_decision.process_lock import ProcessLock  # noqa: E402

_SUP_LOCK = os.path.join(_PARENT, "logs", "hitl-supervisor.lock")
_DAEMON_LOCK = os.path.join(_PARENT, "logs", "hitl-daemon.lock")
_SUPERVISOR = os.path.join(_HERE, "daemon_supervisor.py")
_CLI = os.path.join(_HERE, "cli.py")
_IS_WIN = os.name == "nt"


def _status() -> dict:
    sup = ProcessLock(_SUP_LOCK, "supervisor").status()
    dae = ProcessLock(_DAEMON_LOCK, "daemon").status()
    if sup.state == "running" and dae.state == "running":
        overall = "running"
    elif sup.state in ("missing", "stale") and dae.state in ("missing", "stale"):
        overall = "stopped"
    elif sup.state in ("corrupt", "unverified") or dae.state in ("corrupt", "unverified"):
        overall = "degraded"
    else:
        overall = "degraded"
    return {
        "overall": overall,
        "supervisor": {"state": sup.state, "reason": sup.reason, "info": sup.info},
        "daemon": {"state": dae.state, "reason": dae.reason, "info": dae.info},
    }


def _print(obj, as_json: bool) -> None:
    if as_json or "overall" not in obj:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
        return
    print("HITL lifecycle: %s" % obj.get("overall"))
    for name in ("supervisor", "daemon"):
        s = obj[name]
        info = s.get("info") or {}
        print("  %-10s %-10s pid=%s owner=%s  %s" % (
            name, s["state"], info.get("pid", "-"), info.get("owner", "-"), s["reason"]))


def _owned(info: dict) -> bool:
    return info.get("owner") in ("supervisor", "daemon") and bool(info.get("pid"))


def _terminate(pid: int, tree: bool = False) -> bool:
    if pid <= 0:
        return False
    try:
        if _IS_WIN:
            args = ["taskkill", "/PID", str(pid), "/F"]
            if tree:
                args.insert(3, "/T")
            p = subprocess.run(args, capture_output=True, text=True, timeout=10)
            return p.returncode == 0
        os.kill(pid, 15)
        for _ in range(20):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                return True
        os.kill(pid, 9)
        return True
    except Exception:
        return False


def _clean_stale(path: str, owner: str) -> None:
    lock = ProcessLock(path, owner)
    st = lock.status()
    if st.state in ("stale", "corrupt"):
        ok, _ = lock.acquire()
        if ok:
            lock.release()


def start() -> dict:
    st = _status()
    if st["supervisor"]["state"] in ("running", "unverified"):
        return {"started": False, "reason": "supervisor 已在运行", "status": st}
    python = sys.executable
    if _IS_WIN:
        pyw = python.replace("python.exe", "pythonw.exe")
        if os.path.exists(pyw):
            python = pyw
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([python, _SUPERVISOR], cwd=os.path.dirname(_PARENT),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, close_fds=True)
    else:
        subprocess.Popen([python, _SUPERVISOR], cwd=os.path.dirname(_PARENT),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    for _ in range(100):
        time.sleep(0.1)
        st = _status()
        if st["supervisor"]["state"] == "running" and st["daemon"]["state"] == "running":
            return {"started": True, "status": st}
    st = _status()
    return {"started": st["supervisor"]["state"] == "running",
            "reason": "启动超时；查看 hitl-supervisor.log", "status": st}


def stop() -> dict:
    st = _status()
    stopped = []
    # Windows: supervisor 树杀会带走 daemon；POSIX 先停 supervisor 再停 daemon
    sup_info = st["supervisor"]["info"] or {}
    if _owned(sup_info) and st["supervisor"]["state"] in ("running", "unverified"):
        if _terminate(int(sup_info["pid"]), tree=_IS_WIN):
            stopped.append("supervisor")
    dae_info = st["daemon"]["info"] or {}
    if _owned(dae_info) and st["daemon"]["state"] in ("running", "unverified"):
        if _terminate(int(dae_info["pid"]), tree=False):
            stopped.append("daemon")
    time.sleep(0.5)
    _clean_stale(_SUP_LOCK, "supervisor")
    _clean_stale(_DAEMON_LOCK, "daemon")
    return {"stopped": stopped, "status": _status()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lifecycle.py", description="HITL daemon 生命周期")
    ap.add_argument("command", choices=["status", "start", "stop", "restart", "recover"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.command == "status":
        out = _status()
    elif args.command == "start":
        out = start()
    elif args.command == "stop":
        out = stop()
    elif args.command == "restart":
        out = {"stop": stop(), "start": start()}
    else:  # recover
        started = start()
        rec = {}
        if started.get("status", {}).get("overall") == "running":
            try:
                p = subprocess.run([sys.executable, "-I", _CLI, "recover"],
                                   capture_output=True, text=True, timeout=60)
                rec = {"rc": p.returncode, "output": (p.stdout or "").strip()[:2000]}
            except Exception as e:
                rec = {"rc": -1, "error": str(e)}
        out = {"start": started, "recover": rec}
    _print(out, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
