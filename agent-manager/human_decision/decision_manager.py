# -*- coding: utf-8 -*-
"""HITL — Decision Manager：人工决策生命周期统一编排（唯一入口）。

其他模块不得各自实现独立的人工决策逻辑，一律经本类：
    创建决策请求 → 保存上下文 → 发送钉钉通知 → 等待/接收回复 → 验证回复
    → 更新状态 → 通知等待中的 Agent → 恢复原 Session → 超时/异常/重复处理
"""
from __future__ import annotations

import os
import sys
from typing import Any, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from human_decision.decision_detector import detect  # noqa: E402
from human_decision.decision_store import DecisionStore  # noqa: E402
from human_decision.hitl_config import HitlConfig, load_config  # noqa: E402
from human_decision.models import (  # noqa: E402
    DecisionLevel,
    DecisionOption,
    DecisionRecord,
    DecisionStatus,
    ReplyKind,
    new_decision_id,
    _now,
)
from human_decision.notifier import DingTalkNotifier  # noqa: E402
from human_decision.reply_handler import ReplyHandler  # noqa: E402
from human_decision.session_resumer import SessionResumer  # noqa: E402
from human_decision import recovery_handler, timeout_handler  # noqa: E402

# 复用 P11 审计（execution/{project}/{task}/audit.jsonl），失败不影响主流程；
# 测试环境（HITL_NO_AUDIT=1 / pytest）不写真实 execution/ 树。
_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


def _audit(task_id, action, detail=None, project_key=None):
    if os.environ.get("HITL_NO_AUDIT") or os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    try:
        from audit import audit as _real_audit  # type: ignore

        return _real_audit(task_id, action, detail, project_key=project_key)
    except Exception:
        return None


class DecisionManager:
    """统一编排。线程安全由 DecisionStore 的锁保证。"""

    def __init__(
        self,
        cfg: HitlConfig | None = None,
        store: DecisionStore | None = None,
        notifier=None,
        resumer=None,
        *,
        logger=None,
    ):
        self.cfg = cfg or load_config()
        self.store = store or DecisionStore()
        self._log = logger or (lambda m: None)
        self.notifier = notifier if notifier is not None else DingTalkNotifier(self.cfg, logger=self._log)
        self.resumer = resumer if resumer is not None else SessionResumer(self.cfg, self.store, logger=self._log)
        self.replies = ReplyHandler(self.cfg, self.store, self.resumer, self.notifier, logger=self._log)

    # ------------------------------------------------------- 创建
    def create_decision(
        self,
        *,
        task_id: str,
        question: str,
        background: str = "",
        options: list[dict] | None = None,
        recommendation: str = "",
        recommend_reason: str = "",
        risk: str = "",
        level: str | None = None,
        project_key: str = "",
        agent_id: str = "",
        session_id: str = "",
        wait_seconds: int | None = None,
    ) -> DecisionRecord:
        """创建决策并发送钉钉通知。返回 DecisionRecord。"""
        det = detect(question=question, background=background, risk=risk, explicit_level=level)
        if det.level == DecisionLevel.P2 and not level:
            # P2 不应进入人工流程 —— 防止滥用：仍允许创建，但标记理由
            self._log(f"P2 级决策被请求（{det.reason}），按 Agent 显式要求进入流程")

        opts = [
            DecisionOption(id=str(o["id"]), description=str(o.get("description", "")))
            for o in (options or [])
        ]
        cc_project = os.environ.get("CC_PROJECT", "")
        cc_session_key = os.environ.get("CC_SESSION_KEY", "")
        sid = session_id or self.resumer._query_agent_sid(cc_project, cc_session_key)

        wait = wait_seconds if wait_seconds is not None else self.cfg.tool_wait_seconds
        # 超时提醒/超时标记的绝对时间锚点 = 通知时间；deadline 供 UI 展示
        rec = DecisionRecord(
            decision_id=new_decision_id(task_id),
            task_id=str(task_id),
            level=det.level,
            question=question,
            background=background,
            options=opts,
            recommended_option=recommendation or None,
            recommend_reason=recommend_reason,
            risk=risk,
            project_key=project_key,
            agent_id=agent_id,
            session_id=sid,
            cc_project=cc_project,
            cc_session_key=cc_session_key,
        )
        self.store.create(rec)
        self.store.log_event(rec.decision_id, "detection", det.to_dict())
        try:
            _audit(rec.task_id, "human_decision.create",
                   {"decision_id": rec.decision_id, "level": rec.level.value,
                    "question": question[:100]}, project_key=rec.project_key or None)
        except Exception:
            pass

        res = self.notifier.send_decision_request(rec)
        if res.get("sent"):
            self.store.transition(rec.decision_id, DecisionStatus.WAITING_REPLY,
                                  allowed_from={DecisionStatus.CREATED},
                                  fields={"notified_at": _now()})
        else:
            self.store.transition(rec.decision_id, DecisionStatus.NOTIFY_FAILED,
                                  allowed_from={DecisionStatus.CREATED},
                                  fields={"notified_at": _now(),
                                          "last_error": res.get("error", "")[:300]})
            self._log(f"决策通知失败（决策继续等待，不放行）: {res.get('error')}")
        # T06：任务进入等待人工决策态（可选回调，不影响无回调场景）
        self._notify_task_state(rec.task_id, "WAITING_HUMAN", rec.decision_id)
        return self.store.get(rec.decision_id) or rec

    def _notify_task_state(self, task_id: str, state: str, decision_id: str = "") -> None:
        """桥接 TaskState（T06）：决策创建/完成时同步任务状态。"""
        hook = getattr(self, "task_state_hook", None)
        if hook:
            try:
                hook(task_id=task_id, state=state, decision_id=decision_id)
            except Exception as e:
                self._log(f"task_state_hook 异常（不影响决策）: {e}")

    # ------------------------------------------------------- 等待（有界）
    def wait_for_decision(self, decision_id: str, wait_seconds: int | None = None) -> dict:
        """有界等待用户回复。轮询期间同时收集回复（无需 daemon 也能闭环）。

        返回：
            {"outcome": "decided",  "decision": {...}}     用户已决策（含 STOP）
            {"outcome": "suspended", "decision": {...}}    等待超时 → 安全挂起
            {"outcome": "timeout_pending", ...}            已标记 DECISION_TIMEOUT
        """
        import time

        wait = wait_seconds if wait_seconds is not None else self.cfg.tool_wait_seconds
        self.store.log_event(decision_id, "tool_waiting", {"wait_seconds": wait})
        deadline = time.monotonic() + max(1, wait)
        while time.monotonic() < deadline:
            self.poll_once()
            rec = self.store.get(decision_id)
            if rec is None:
                return {"outcome": "unknown", "reason": f"决策 {decision_id} 不存在"}
            if rec.status in (DecisionStatus.DECISION_RECEIVED, DecisionStatus.RESUMING,
                              DecisionStatus.RESUMED, DecisionStatus.REJECTED):
                return {"outcome": "decided", "decision": rec.to_dict()}
            if rec.status == DecisionStatus.COMPLETED:
                return {"outcome": "decided", "decision": rec.to_dict()}
            time.sleep(self.cfg.poll_interval_seconds)

        # 有界等待到期 → 安全挂起（绝不放行未批准操作）
        self.store.log_event(decision_id, "tool_suspended", {"waited_seconds": wait})
        rec = self.store.get(decision_id)
        return {"outcome": "suspended", "decision": rec.to_dict() if rec else None,
                "instruction": (
                    "决策仍在等待人工回复。请立即结束当前执行（不要继续任何依赖该决策的高风险操作），"
                    "在最终输出中说明：任务已挂起等待决策 <decision_id>。"
                    f"决策返回后将通过原 Session 恢复执行（见 execution/ 下 human-decision 恢复包）。"
                )}

    def poll_once(self) -> list[dict]:
        """收集一次回复（watch 源）+ 超时扫描。返回处理结果。"""
        results = []
        if self.cfg.watch_session_files:
            try:
                results = self.replies.collect_from_session_files()
            except Exception as e:
                self._log(f"收集回复失败: {e}")
        try:
            timeout_handler.check_timeouts(self.store, self.cfg, self.notifier, logger=self._log)
        except Exception as e:
            self._log(f"超时扫描失败: {e}")
        return results

    # ------------------------------------------------------- 回复入口
    def apply_reply(self, **kwargs) -> dict:
        r = self.replies.handle(**kwargs)
        if r.get("outcome") == "accepted":
            try:
                rec = self.store.get(r.get("decision_id", ""))
                _audit(rec.task_id if rec else kwargs.get("task_id", ""), "human_decision.reply",
                       {"decision_id": r.get("decision_id"), "choice": r.get("choice"),
                        "comment": (r.get("comment") or "")[:100],
                        "user": kwargs.get("user_name") or kwargs.get("user_id")},
                       project_key=(rec.project_key if rec else "") or None)
            except Exception:
                pass
        return r

    def apply_hook_env(self, env: dict | None = None) -> dict:
        return self.replies.handle_hook_env(env)

    # ------------------------------------------------------- 查询
    def get_decision(self, decision_id: str) -> Optional[dict]:
        rec = self.store.get(decision_id)
        if not rec:
            return None
        d = rec.to_dict()
        d["replies"] = self.store.replies(decision_id)
        d["events"] = self.store.events(decision_id)
        return d

    def list_decisions(self, *, status: str | None = None, task_id: str | None = None,
                       project_key: str | None = None, limit: int = 50) -> list[dict]:
        recs = self.store.list(status=status, task_id=task_id, project_key=project_key, limit=limit)
        return [r.to_dict() for r in recs]

    def pending_for_task(self, task_id: str) -> list[dict]:
        return [r.to_dict() for r in self.store.list_waiting() if r.task_id == str(task_id)]

    # ------------------------------------------------------- 运维
    def recover(self) -> dict:
        return recovery_handler.recover(self.store, self.cfg, self.notifier, logger=self._log)

    def check_timeouts(self) -> dict:
        return timeout_handler.check_timeouts(self.store, self.cfg, self.notifier, logger=self._log)

    def complete(self, decision_id: str) -> bool:
        """Agent 完成任务后确认决策闭环（RESUMED → COMPLETED）。"""
        rec = self.store.get(decision_id)
        ok = self.store.transition(
            decision_id, DecisionStatus.COMPLETED,
            allowed_from={DecisionStatus.RESUMED, DecisionStatus.REJECTED},
            fields={"completed_at": _now()},
        )
        if ok and rec:
            self._notify_task_state(rec.task_id, "RUNNING", decision_id)  # T06: 决策闭环后任务恢复
        return ok
