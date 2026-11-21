# -*- coding: utf-8 -*-
"""HITL — CLI 入口（daemon / hook / reply / status / create / complete）。

用法：
    python cli.py daemon                     # 常驻：恢复对账 + 收集回复 + 超时扫描
    python cli.py hook                       # cc-connect command hook 回调（读 CC_HOOK_*）
    python cli.py serve [--port 9411]        # HTTP hook 端点（cc-connect type=http）
    python cli.py reply --text "A" [...]     # 手动注入回复（测试/补录）
    python cli.py create --task 3413 ...     # 手动创建决策（测试）
    python cli.py status [--decision-id X]   # 查询
    python cli.py recover                    # 启动对账
    python cli.py complete --decision-id X   # 标记闭环完成
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
for _p in (_PARENT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from human_decision.decision_manager import DecisionManager  # noqa: E402


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _daemon_lock_path() -> str:
    return os.path.join(_PARENT, "logs", "hitl-daemon.lock")


def _pid_alive(pid: int) -> bool:
    """Windows 安全的存活探测（os.kill(pid,0) 在 Windows 是 TerminateProcess，禁用）。"""
    if pid <= 0:
        return False
    try:
        import psutil  # type: ignore

        return psutil.pid_exists(pid)
    except ImportError:
        pass
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _acquire_daemon_lock(path: str) -> bool:
    """单实例保护：PID 锁文件 + 陈旧锁自动接管。返回 True=获得锁。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            return True
        except FileExistsError:
            try:
                with open(path, encoding="utf-8") as f:
                    old_pid = int((f.read() or "0").strip() or "0")
            except (OSError, ValueError):
                old_pid = 0
            if _pid_alive(old_pid):
                return False  # 已有存活实例
            # 陈旧锁 → 收回
            try:
                os.unlink(path)
            except OSError:
                return False
    return False


def _release_daemon_lock(path: str) -> None:
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return
    # Windows 下必须先关闭文件句柄再 unlink，否则删除被拒绝
    if (content or "").strip() == str(os.getpid()):
        try:
            os.unlink(path)
        except OSError:
            pass


def cmd_daemon(mgr: DecisionManager, args) -> int:
    lock_path = _daemon_lock_path()
    if not _acquire_daemon_lock(lock_path):
        _print({"event": "daemon_already_running", "lock": lock_path})
        return 2
    try:
        summary = mgr.recover()
        _print({"event": "recovered", **summary})
        interval = max(1.0, float(args.interval))
        try:
            while True:
                results = mgr.poll_once()
                for r in results:
                    _print({"event": "reply_processed", **r})
                time.sleep(interval)
        except KeyboardInterrupt:
            _print({"event": "daemon_stopped"})
            return 0
    finally:
        _release_daemon_lock(lock_path)


def cmd_hook(mgr: DecisionManager, args) -> int:
    r = mgr.apply_hook_env()
    _print(r)
    # hook 失败不应影响 cc-connect 主流程：恒 rc=0
    return 0


def cmd_serve(mgr: DecisionManager, args) -> int:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 静默默认日志
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8", "replace")
            try:
                payload = json.loads(body or "{}")
                r = mgr.replies.handle_hook_payload(payload if isinstance(payload, dict) else {})
            except Exception as e:
                r = {"outcome": "error", "reason": str(e)[:200]}
            data = json.dumps(r, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            data = json.dumps({"ok": True, "service": "hitl-hook"}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    host = mgr.cfg.hook_endpoint_host
    port = args.port or mgr.cfg.hook_endpoint_port
    srv = HTTPServer((host, port), Handler)
    _print({"event": "hook_server_listening", "host": host, "port": port})
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


def cmd_reply(mgr: DecisionManager, args) -> int:
    r = mgr.apply_reply(
        raw_text=args.text, source="cli",
        user_id=args.user_id or "", user_name=args.user_name or "",
        chat_session_key=args.session_key or "",
    )
    _print(r)
    return 0 if r.get("outcome") in ("accepted", "duplicate") else 1


def cmd_create(mgr: DecisionManager, args) -> int:
    options = []
    if args.options:
        for pair in args.options.split("|"):
            oid, _, desc = pair.partition(":")
            if oid:
                options.append({"id": oid.strip(), "description": desc.strip()})
    rec = mgr.create_decision(
        task_id=args.task, question=args.question,
        background=args.background or "", options=options,
        recommendation=args.recommendation or "", risk=args.risk or "",
        level=args.level or None, project_key=args.project_key or "",
    )
    _print(rec.to_dict())
    return 0


def cmd_status(mgr: DecisionManager, args) -> int:
    if args.decision_id:
        _print(mgr.get_decision(args.decision_id) or {"found": False})
    else:
        _print({"decisions": mgr.list_decisions(limit=args.limit)})
    return 0


def cmd_recover(mgr: DecisionManager, args) -> int:
    _print(mgr.recover())
    return 0


def cmd_complete(mgr: DecisionManager, args) -> int:
    ok = mgr.complete(args.decision_id)
    _print({"decision_id": args.decision_id, "completed": ok})
    return 0 if ok else 1


def cmd_poll(mgr: DecisionManager, args) -> int:
    results = mgr.poll_once()
    _print({"results": results})
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="HITL Human Decision CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("daemon", help="常驻：恢复 + 收集回复 + 超时扫描")
    sp.add_argument("--interval", default="3")
    sp.set_defaults(fn=cmd_daemon)

    sp = sub.add_parser("hook", help="cc-connect command hook 回调")
    sp.set_defaults(fn=cmd_hook)

    sp = sub.add_parser("serve", help="HTTP hook 端点")
    sp.add_argument("--port", type=int, default=0)
    sp.set_defaults(fn=cmd_serve)

    sp = sub.add_parser("reply", help="手动注入回复")
    sp.add_argument("--text", required=True)
    sp.add_argument("--user-id", default="")
    sp.add_argument("--user-name", default="")
    sp.add_argument("--session-key", default="")
    sp.set_defaults(fn=cmd_reply)

    sp = sub.add_parser("create", help="手动创建决策（测试）")
    sp.add_argument("--task", required=True)
    sp.add_argument("--question", required=True)
    sp.add_argument("--background", default="")
    sp.add_argument("--options", default="", help='如 "A:方案A|B:方案B"')
    sp.add_argument("--recommendation", default="")
    sp.add_argument("--risk", default="")
    sp.add_argument("--level", default="")
    sp.add_argument("--project-key", default="")
    sp.set_defaults(fn=cmd_create)

    sp = sub.add_parser("status", help="查询决策")
    sp.add_argument("--decision-id", default="")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("recover", help="启动对账")
    sp.set_defaults(fn=cmd_recover)

    sp = sub.add_parser("complete", help="标记闭环完成")
    sp.add_argument("--decision-id", required=True)
    sp.set_defaults(fn=cmd_complete)

    sp = sub.add_parser("poll", help="收集一轮回复（单次）")
    sp.set_defaults(fn=cmd_poll)

    args = p.parse_args(argv)
    mgr = DecisionManager()
    try:
        return args.fn(mgr, args)
    finally:
        mgr.store.close()


if __name__ == "__main__":
    sys.exit(main())
