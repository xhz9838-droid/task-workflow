# -*- coding: utf-8 -*-
"""P11.1 CLI 通用设施 —— 退出码、输出、配置加载。

统一约定（runner.py / monitor.py 共用）：
    退出码  0 成功 | 1 失败 | 2 用法错误 | 3 未找到 | 4 已在运行 | 5 阻塞
    输出    UTF-8（Windows GBK 控制台安全）
    配置    agent-manager/config.yaml（PyYAML 缺失时用内置默认，不硬依赖）
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# --------------------------------------------------------------- 退出码
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_LOCKED = 4
EXIT_BLOCKED = 5

EXIT_NAMES = {
    EXIT_OK: "OK",
    EXIT_FAILED: "FAILED",
    EXIT_USAGE: "USAGE",
    EXIT_NOT_FOUND: "NOT_FOUND",
    EXIT_LOCKED: "LOCKED",
    EXIT_BLOCKED: "BLOCKED",
}

CONFIG_PATH = os.path.join(_HERE, "config.yaml")
DEFAULT_DB = os.path.join(_HERE, "logs", "agent_manager.db")


# --------------------------------------------------------------- 输出
def configure_stdout() -> None:
    """Windows 控制台可能是 GBK，统一强制 UTF-8，避免中文/emoji 崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def log(msg: str) -> None:
    print(msg)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def err(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


# --------------------------------------------------------------- 配置
_DEFAULTS = {
    "execution": {
        "max_concurrent_tasks": 1,
        "task_lock_enabled": True,
        "resume_enabled": True,
        "task_lock_ttl_seconds": 3600,
        "default_budget_seconds": 1800,
    },
    "routing": {
        "simple": {"subagents": False, "workflow": "direct"},
        "medium": {"workflow": "selective"},
        "large": {"workflow": "full"},
    },
    "monitor": {
        "poll_interval_seconds": 5,
        "heartbeat_timeout_seconds": 300,
        "default_task_timeout_seconds": 1800,
        "output_idle_warning_seconds": 300,
    },
    "retry": {
        "max_attempts": 2,
        "initial_delay_seconds": 30,
        "max_delay_seconds": 300,
        "exponential_backoff": True,
    },
    "verification": {
        "run_build_by_default": False,
        "aggregate_blocked_checks": True,
        "require_evidence": True,
    },
    "jenkins": {
        "enabled": False,
        "mock": True,
        "allowed_job_prefix": "ai-test-",
        "timeout_seconds": 1800,
    },
    "notification": {
        "enabled": True,
        "reuse_existing_channel": True,
        "silent_events": ["agent_thinking", "tool_call", "progress_tick"],
    },
    "zentao": {
        "enabled": True,
        "dry_run": True,
        "allow_auto_finish": False,
        "allow_auto_close": False,
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | None = None) -> dict:
    """加载 agent-manager/config.yaml。缺失/无 PyYAML 时用内置默认（不硬依赖）。"""
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _DEFAULTS.items()}
    p = path or CONFIG_PATH
    if not os.path.exists(p):
        return cfg
    try:
        import yaml  # type: ignore

        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return _deep_merge(cfg, data)
    except Exception as e:
        warn(f"配置加载失败，使用内置默认: {e}")
        return cfg


# --------------------------------------------------------------- 便捷
def table(rows: list[list[str]], headers: list[str]) -> str:
    """简单表格渲染（无第三方依赖）。"""
    cols = len(headers)
    rows = [list(r) + [""] * (cols - len(r)) for r in rows]
    widths = [len(str(headers[i])) for i in range(cols)]
    for r in rows:
        for i in range(cols):
            widths[i] = max(widths[i], len(str(r[i])))
    line = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    sep = "  ".join("-" * widths[i] for i in range(cols))
    body = ["  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)) for r in rows]
    return "\n".join([line, sep] + body)


def truncate(s: str, n: int = 60) -> str:
    s = str(s) if s is not None else ""
    return s if len(s) <= n else s[: n - 1] + "…"
