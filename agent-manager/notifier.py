# -*- coding: utf-8 -*-
"""P11 Phase 4 — Notifier：钉钉事件通知。

**复用现有 CC Connect 钉钉通道**（`cc-connect send`）。
**不创建新机器人、不新增应用、不假设存在 Python 直连接口**。

策略（P11 §八）：
    - 只在关键节点通知，不每次工具调用都通知
    - 不把普通 Agent 思考过程发到钉钉
    - 同一事件不重复通知（去重）
    - 通知失败**记录但不导致开发任务失败**

通知内容必含：ZenTao 任务号、任务名、任务等级、当前阶段、执行状态、
耗时、失败/成功摘要、Git commit、测试结果、是否需人工操作。
"""
from __future__ import annotations

import datetime
import hashlib
import os
import subprocess
import sys
import tempfile
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from .exceptions import NotifyError
    from .state_manager import StateManager
except ImportError:
    from exceptions import NotifyError  # type: ignore
    from state_manager import StateManager  # type: ignore

NOTIFY_SH = os.path.join(_ROOT, "scripts", "notify.sh")

# 关键事件类型（P11 §八.1）
EVENT_TYPES = {
    "task_started",
    "agent_start_failed",
    "agent_timeout",
    "agent_crashed",
    "auto_retry",
    "human_needed",
    "qa_failed",
    "qa_done",
    "final_success",
    "final_failure",
    "zentao_write_failed",
    "jenkins_result",
}

# 通知等级（决定是否发送）
SILENT_EVENTS = {"agent_thinking", "tool_call", "progress_tick"}


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class Notifier:
    """CC Connect 钉钉通知。事件去重 + 失败不阻塞。"""

    def __init__(
        self,
        *,
        enabled: bool = True,
        state: StateManager | None = None,
        dry_run: bool = False,
        logger=None,
    ):
        self.enabled = enabled
        self.state = state
        self.dry_run = dry_run
        self._log = logger or (lambda m: None)
        self._sent_keys: set[str] = set()

    # ------------------------------------------------------- 事件去重
    @staticmethod
    def _dedupe_key(project_key: str, task_id: str, event_type: str, content_hash: str) -> str:
        raw = f"{project_key}|{task_id}|{event_type}|{content_hash}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _already_sent(self, key: str) -> bool:
        return key in self._sent_keys

    # ------------------------------------------------------- 主入口
    def notify(
        self,
        *,
        project_key: str,
        task_id: str,
        event_type: str,
        task_name: str = "",
        task_level: str = "",
        stage: str = "",
        status: str = "",
        elapsed_seconds: float = 0.0,
        summary: str = "",
        commit: str = "",
        test_results: str = "",
        needs_human: bool = False,
        blocker_id: str = "-",
    ) -> dict:
        """发送通知。返回 {sent, deduped, error}。

        **通知失败不抛异常**，只记录 —— 不导致开发任务失败。
        """
        # 静默事件直接跳过
        if event_type in SILENT_EVENTS:
            return {"sent": False, "deduped": False, "skipped": "silent_event"}

        if not self.enabled:
            return {"sent": False, "deduped": False, "skipped": "disabled"}

        body = self._build_body(
            project_key=project_key,
            task_id=task_id,
            event_type=event_type,
            task_name=task_name,
            task_level=task_level,
            stage=stage,
            status=status,
            elapsed_seconds=elapsed_seconds,
            summary=summary,
            commit=commit,
            test_results=test_results,
            needs_human=needs_human,
        )

        key = self._dedupe_key(project_key, task_id, event_type, hashlib.md5(body.encode()).hexdigest()[:8])
        if self._already_sent(key):
            return {"sent": False, "deduped": True}

        if self.dry_run:
            self._sent_keys.add(key)
            self._log(f"[dry-run] 通知 {event_type}: {body[:80]}")
            return {"sent": True, "deduped": False, "dry_run": True, "body": body}

        try:
            self._send_via_ccconnect(task_id, stage, blocker_id, body, project_key)
            self._sent_keys.add(key)
            return {"sent": True, "deduped": False}
        except Exception as e:
            # 失败记录但不阻塞开发任务
            self._log(f"通知失败（不影响开发）: {e}")
            return {"sent": False, "deduped": False, "error": str(e)[:200]}

    # ------------------------------------------------------- 消息体
    def _build_body(self, **kw) -> str:
        lines = []
        lines.append(f"【事件】{kw['event_type']}")
        if kw.get("task_name"):
            lines.append(f"任务: #{kw['task_id']} {kw['task_name']}")
        else:
            lines.append(f"任务: #{kw['task_id']}")
        if kw.get("task_level"):
            lines.append(f"等级: {kw['task_level']}")
        if kw.get("stage"):
            lines.append(f"阶段: {kw['stage']}")
        if kw.get("status"):
            lines.append(f"状态: {kw['status']}")
        if kw.get("elapsed_seconds"):
            lines.append(f"耗时: {int(kw['elapsed_seconds'])}s")
        if kw.get("commit"):
            lines.append(f"Commit: {kw['commit'][:8]}")
        if kw.get("test_results"):
            lines.append(f"测试: {kw['test_results']}")
        if kw.get("summary"):
            lines.append(f"摘要: {kw['summary']}")
        lines.append(f"需人工: {'是' if kw.get('needs_human') else '否'}")
        return "\n".join(lines)

    # ------------------------------------------------------- 发送
    def _send_via_ccconnect(self, task_id: str, stage: str, blocker_id: str, body: str, project_key: str) -> None:
        """经现有 notify.sh → cc-connect send。"""
        if not os.path.exists(NOTIFY_SH):
            raise NotifyError(f"通知脚本不存在: {NOTIFY_SH}")

        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(body)
            body_file = f.name

        try:
            p = subprocess.run(
                ["bash", NOTIFY_SH, str(task_id), stage or "-", blocker_id or "-", body_file],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                env=dict(os.environ, PYTHONIOENCODING="utf-8", PROJECT_KEY=project_key),
            )
            if p.returncode != 0:
                raise NotifyError(f"notify.sh rc={p.returncode}: {(p.stderr or p.stdout)[:150]}")
        finally:
            try:
                os.unlink(body_file)
            except OSError:
                pass

    # ------------------------------------------------------- 便捷方法
    def task_started(self, **kw) -> dict:
        return self.notify(event_type="task_started", **kw)

    def agent_start_failed(self, **kw) -> dict:
        return self.notify(event_type="agent_start_failed", needs_human=True, **kw)

    def agent_timeout(self, **kw) -> dict:
        return self.notify(event_type="agent_timeout", needs_human=True, **kw)

    def agent_crashed(self, **kw) -> dict:
        return self.notify(event_type="agent_crashed", needs_human=True, **kw)

    def auto_retry(self, **kw) -> dict:
        return self.notify(event_type="auto_retry", **kw)

    def human_needed(self, **kw) -> dict:
        return self.notify(event_type="human_needed", needs_human=True, **kw)

    def qa_done(self, **kw) -> dict:
        return self.notify(event_type="qa_done", **kw)

    def qa_failed(self, **kw) -> dict:
        return self.notify(event_type="qa_failed", needs_human=True, **kw)

    def final_success(self, **kw) -> dict:
        return self.notify(event_type="final_success", **kw)

    def final_failure(self, **kw) -> dict:
        return self.notify(event_type="final_failure", needs_human=True, **kw)

    def zentao_write_failed(self, **kw) -> dict:
        return self.notify(event_type="zentao_write_failed", **kw)

    def jenkins_result(self, **kw) -> dict:
        return self.notify(event_type="jenkins_result", **kw)
