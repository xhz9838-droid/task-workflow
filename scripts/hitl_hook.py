# -*- coding: utf-8 -*-
"""安装/卸载 Claude Code HITL UserPromptSubmit Hook（幂等，保留其他配置）。

用法：
    python -I scripts/hitl_hook.py install --settings <path> --command <cmd> --root <workflow_home>
    python -I scripts/hitl_hook.py uninstall --settings <path>
    python -I scripts/hitl_hook.py status --settings <path> --root <workflow_home> [--json]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys

MARKER = "human_decision/prompt_router.py"


def _load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("settings 顶层不是 JSON 对象")
    return data


def _save(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    if os.path.exists(path):
        stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy2(path, "%s.bak.%s" % (path, stamp))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _entries(data: dict) -> list:
    return ((data.get("hooks") or {}).get("UserPromptSubmit") or [])


def _is_ours(entry: dict) -> bool:
    for h in (entry.get("hooks") or []):
        if isinstance(h, dict) and MARKER in str(h.get("command") or "").replace("\\", "/"):
            return True
    return False


def _ours(data: dict) -> list:
    return [e for e in _entries(data) if _is_ours(e)]


def install(settings: str, command: str, root: str) -> dict:
    data = _load(settings)
    hooks = data.setdefault("hooks", {})
    entries = [e for e in (hooks.get("UserPromptSubmit") or []) if not _is_ours(e)]
    entries.append({"hooks": [{"type": "command", "command": command}]})
    hooks["UserPromptSubmit"] = entries
    _save(settings, data)
    return status(settings, root)


def uninstall(settings: str) -> dict:
    data = _load(settings)
    hooks = data.get("hooks") or {}
    entries = [e for e in (hooks.get("UserPromptSubmit") or []) if not _is_ours(e)]
    if entries:
        hooks["UserPromptSubmit"] = entries
    else:
        hooks.pop("UserPromptSubmit", None)
    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)
    _save(settings, data)
    return status(settings, "")


def status(settings: str, root: str) -> dict:
    try:
        data = _load(settings)
    except Exception as e:  # noqa: BLE001
        return {"state": "error", "reason": "%s: %s" % (type(e).__name__, e), "count": 0}
    ours = _ours(data)
    if not ours:
        return {"state": "not_installed", "count": 0}
    if len(ours) > 1:
        return {"state": "mismatch", "reason": "存在多个本工作流 Hook", "count": len(ours)}
    cmd = ours[0]["hooks"][0].get("command", "")
    expected = (os.path.join(os.path.abspath(root), "agent-manager", "human_decision",
                             "prompt_router.py").replace("\\", "/") if root else "")
    path_ok = expected in cmd.replace("\\", "/") if expected else True
    return {
        "state": "ok" if path_ok else "mismatch",
        "count": 1,
        "command": cmd,
        "expected_path": expected,
        "path_ok": path_ok,
        "reason": "" if path_ok else "Hook 指向其他工作流根（需升级重装）",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hitl_hook.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("install")
    pi.add_argument("--settings", required=True)
    pi.add_argument("--command", required=True)
    pi.add_argument("--root", required=True)
    pu = sub.add_parser("uninstall")
    pu.add_argument("--settings", required=True)
    ps = sub.add_parser("status")
    ps.add_argument("--settings", required=True)
    ps.add_argument("--root", default="")
    ps.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        r = install(args.settings, args.command, args.root) if args.cmd == "install" else (
            uninstall(args.settings) if args.cmd == "uninstall" else status(args.settings, args.root))
    except Exception as e:  # noqa: BLE001 —— 安装失败必须非零
        print(json.dumps({"state": "error", "reason": "%s: %s" % (type(e).__name__, e)},
                         ensure_ascii=False))
        return 1
    print(json.dumps(r, ensure_ascii=False, indent=2 if getattr(args, "json", False) else None))
    if args.cmd == "status" and r.get("state") == "error":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
