# -*- coding: utf-8 -*-
"""ZenTao Reporter：禅道进度/结果回写。

复用现有 ZenTao 适配器（`scripts/zt.py` + `~/.claude/skills/zentao-tasks`）。
不新建第二套 ZenTao Client。

约束：
    - 更新保留原任务描述（追加，不覆盖）
    - 不覆盖原有备注或他人信息
    - 不伪造工时/完成日期
    - 遵循状态流转：wait→doing 须满足必填字段
    - task_finish（doing→done）：Verifier 门禁通过后自动执行，读回确认
    - task_close（done→closed）：关闭条件满足后自动执行，读回确认；不满足暂缓并记录原因
    - finish 与 close 记录任务 ID、执行 ID、前后状态、结果与失败原因
    - 写入后必须读回禅道状态确认结果
    - 回写失败保存待写事件，不丢执行结果
    - 重试回写避免重复追加相同记录（幂等）
    - 回写后读回核验
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from typing import Any, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from .exceptions import ZenTaoWriteError
    from .state_manager import StateManager
except ImportError:
    from exceptions import ZenTaoWriteError  # type: ignore
    from state_manager import StateManager  # type: ignore

ZT_SCRIPT = os.path.join(_ROOT, "scripts", "zt.py")
AUDIT_SCRIPT = os.path.join(_ROOT, "scripts", "audit.py")


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class ZenTaoReporter:
    """禅道回写。写入经适配器 + 读回核验。"""

    def __init__(self, state: StateManager | None = None, *, dry_run: bool = False, logger=None):
        self.state = state
        self.dry_run = dry_run
        self._log = logger or (lambda m: None)

    # ------------------------------------------------------- 查询
    def get_task(self, task_id: str, timeout: int = 60) -> dict:
        """读取任务详情（只读）。"""
        out = self._run_zt(["detail", "--task", str(task_id)], timeout=timeout)
        try:
            return json.loads(out)
        except Exception as e:
            raise ZenTaoWriteError(f"解析任务详情失败: {e} | {out[:200]}")

    def verify_owner(self, task_id: str, expected_account: str) -> bool:
        """核验任务归属本人（禁止操作他人任务）。"""
        t = self.get_task(task_id)
        owner = t.get("assignedTo") or ""
        ok = str(owner).strip() == expected_account.strip()
        if not ok:
            self._log(f"任务 {task_id} 归属 {owner} != {expected_account}，拒绝操作")
        return ok

    # ------------------------------------------------------- 进度回写
    def report_progress(
        self,
        *,
        task_id: str,
        project_key: str,
        stage: str,
        text: str,
        attempt: int = 1,
    ) -> dict:
        """追加进度到任务 desc（不覆盖原文）。回写后读回核验。"""
        payload = {"stage": stage, "text": text, "at": _now(), "attempt": attempt}

        if self.dry_run:
            self._log(f"[dry-run] 进度回写 task={task_id} stage={stage}")
            return {"ok": True, "dry_run": True, "payload": payload}

        try:
            out = self._run_zt(
                ["progress", "--task", str(task_id), "--stage", stage, "--text", text],
                timeout=90,
            )
        except Exception as e:
            # 失败 → 存待写事件，不丢结果
            self._enqueue(task_id, project_key, "progress", payload, str(e))
            raise ZenTaoWriteError(f"进度回写失败（已存待写队列）: {e}")

        # 读回核验（zt.py 内部已做；这里再确认输出含标记）
        marker = f"[AI-{task_id}-{stage}]"
        verified = marker in out or "已写入" in out or "跳过" in out
        result = {"ok": verified, "output_tail": out[-300:], "payload": payload}
        if not verified:
            self._enqueue(task_id, project_key, "progress", payload, "读回未见标记")
            raise ZenTaoWriteError(f"进度回写读回未确认: {out[-200:]}")
        return result

    # ------------------------------------------------------- 工作日志/工时
    def report_worklog(
        self,
        *,
        task_id: str,
        project_key: str,
        stage: str,
        progress: float,
        work: str,
        date: str = "",
        total_hours: float | None = None,
    ) -> dict:
        """记录阶段工作日志（增量 consumed），不改变任务完成状态。

        工时由 scripts/worklog.py 统一计算：计划工作日×8 或 estimate；
        无基线时拒绝（不编造）。写日志与 finish 相互独立。
        """
        payload = {
            "stage": stage, "progress": progress, "work": work,
            "date": date, "total_hours": total_hours, "at": _now(),
        }
        if self.dry_run:
            self._log(f"[dry-run] 工作日志 task={task_id} stage={stage} progress={progress}")
            return {"ok": True, "dry_run": True, "payload": payload}

        args = [
            "worklog", "--task", str(task_id), "--stage", stage,
            "--progress", str(progress), "--work", work,
        ]
        if date:
            args += ["--date", date]
        if total_hours is not None:
            args += ["--total-hours", str(total_hours)]
        try:
            out = self._run_zt(args, timeout=120)
        except Exception as e:
            self._enqueue(task_id, project_key, "worklog", payload, str(e))
            raise ZenTaoWriteError(f"工作日志写入失败（已存待写队列）: {e}")

        try:
            result = json.loads((out or "").strip().splitlines()[-1])
        except Exception:
            self._enqueue(task_id, project_key, "worklog", payload, "输出无法解析")
            raise ZenTaoWriteError(f"工作日志结果无法解析: {out[-200:]}")
        if not result.get("ok"):
            self._enqueue(task_id, project_key, "worklog", payload,
                          result.get("error", "unknown"))
            raise ZenTaoWriteError(f"工作日志未成功: {result.get('error') or result}")
        result["payload"] = payload
        return result

    # ------------------------------------------------------- Agent 结果
    def report_agent_result(
        self,
        *,
        task_id: str,
        project_key: str,
        agent_name: str,
        status: str,
        commit: str = "",
        tests_summary: str = "",
        error: str = "",
    ) -> dict:
        """记录 Agent 执行结果（进度追加）。"""
        parts = [f"Agent {agent_name}: {status}"]
        if commit:
            parts.append(f"commit={commit[:8]}")
        if tests_summary:
            parts.append(f"测试: {tests_summary}")
        if error:
            parts.append(f"错误: {error[:150]}")
        return self.report_progress(
            task_id=task_id,
            project_key=project_key,
            stage=f"agent-{agent_name}",
            text=" | ".join(parts),
        )

    def report_verification(self, *, task_id: str, project_key: str, verify_dict: dict) -> dict:
        """记录验证结果（PASS/FAIL/BLOCKED/SKIPPED/NOT_RUN）。"""
        tests = verify_dict.get("tests", {})
        summary = ", ".join(f"{k}={v}" for k, v in tests.items())
        overall = verify_dict.get("overall", "NOT_RUN")
        blocked = verify_dict.get("blocked_summary") or ""
        text = f"验证 overall={overall} | {summary}"
        if blocked:
            text += f" | {blocked[:120]}"
        return self.report_progress(
            task_id=task_id, project_key=project_key, stage="verification", text=text
        )

    # ------------------------------------------------------- 状态流转（人工把关）
    def can_start(self, task_detail: dict) -> tuple[bool, str]:
        """wait→doing 前置检查（禅道必填字段）。不满足则说明缺什么。"""
        missing = []
        for f in ("estStarted", "deadline"):
            if not task_detail.get(f):
                missing.append(f)
        if missing:
            return False, f"缺少必填字段: {', '.join(missing)}（不自行估算，需本人提供）"
        return True, ""

    def can_finish(self, *, verifier_passed: bool = False, human_confirmed: bool = False,
                   consumed=None, left=None) -> tuple[bool, str]:
        """doing→done 前置检查。

        门禁通过 → 自动执行；未经门禁 → 需人工确认。
        """
        if not verifier_passed and not human_confirmed:
            return False, "Verifier 质量门禁未通过且无人工确认，不执行 task_finish"
        if consumed is None or left is None:
            return False, "consumed/left 未提供，不推算工时"
        return True, ""

    def can_close(self, *, task_detail: dict | None = None, verifier_passed: bool = False,
                  deliverables_ok: bool = True, records_ok: bool = True) -> tuple[bool, str]:
        """done→closed 关闭条件判断。"""
        status = str((task_detail or {}).get("status") or "").lower()
        if status == "closed":
            return True, "已 closed（幂等，可跳过）"
        if status != "done":
            return False, f"禅道状态 {status or '未知'} 非 done，不满足关闭条件（仅 done→closed）"
        if not verifier_passed:
            return False, "Verifier 验收未通过，暂缓关闭"
        if not deliverables_ok:
            return False, "存在未完成的交付要求，暂缓关闭"
        if not records_ok:
            return False, "必要记录缺失，暂缓关闭"
        return True, ""

    # ------------------------------------------------------- 状态流转执行
    def finish(
        self,
        *,
        task_id: str,
        project_key: str,
        verifier_passed: bool,
        consumed=None,
        left=None,
        finished_date: str | None = None,
        real_started: str | None = None,
        summary: str = "",
        commit: str = "",
        human_confirmed: bool = False,
        exec_id: str = "",
    ) -> dict:
        """执行 task_finish（doing→done）+ **读回确认**。

        - 仅在 Verifier 门禁通过（或人工确认）后执行
        - 工时/日期不推算：consumed/left/finished_date 必须由调用方提供
        - 🔴 完成必须带完成内容（summary）+ git commit id：写入 finished 动作备注，
          **不写任务 desc**；读回核验完成备注含 commit
        - 写入后**必须读回禅道状态确认结果**
        - 与 close 相互独立（finish 与 close 是两个不同生命周期操作）
        """
        ok, reason = self.can_finish(
            verifier_passed=verifier_passed,
            human_confirmed=human_confirmed,
            consumed=consumed,
            left=left,
        )
        if not ok:
            return {"ok": False, "reason": reason, "stage": "precheck"}

        if finished_date is None:
            return {"ok": False, "reason": "finishedDate 未提供，不推算完成日期", "stage": "precheck"}
        if not (summary or "").strip() or not (commit or "").strip():
            return {"ok": False,
                    "reason": "完成内容 summary 与 git commit id 必须提供（写入 finished 动作备注）",
                    "stage": "precheck"}

        payload = {
            "consumed": consumed,
            "left": left,
            "finished_date": finished_date,
            "real_started": real_started,
            "summary": summary,
            "commit": commit,
            "verifier_passed": verifier_passed,
            "exec_id": exec_id,
        }

        if self.dry_run:
            self._log(f"[dry-run] task_finish task={task_id}")
            return {"ok": True, "dry_run": True, "payload": payload}

        args = [
            "finish", "--task", str(task_id),
            "--consumed", str(consumed), "--left", str(left),
            "--finishedDate", finished_date,
            "--work", summary,
            "--commit", commit,
            "--exec-id", exec_id or "",
        ]
        if real_started:
            args += ["--realStarted", real_started]
        try:
            out = self._run_zt(args, timeout=120)
        except Exception as e:
            self._enqueue(task_id, project_key, "finish", payload, str(e))
            raise ZenTaoWriteError(f"task_finish 失败（已存待写队列）: {e}")

        # **读回确认**：必须核实 status 已变 done
        try:
            after = self.get_task(task_id)
        except Exception as e:
            return {"ok": False, "reason": f"finish 已调用但读回失败: {e}", "stage": "readback"}

        status = str(after.get("status", "")).lower()
        confirmed = status == "done"
        result = {
            "ok": confirmed,
            "status_after": status,
            "confirmed": confirmed,
            "output_tail": out[-200:],
            "payload": payload,
        }
        if not confirmed:
            self._log(f"⚠ task_finish 后读回 status={status}（期望 done）")
        return result

    def close(
        self,
        *,
        task_id: str,
        project_key: str,
        comment: str,
        verifier_passed: bool = False,
        deliverables_ok: bool = True,
        records_ok: bool = True,
        exec_id: str = "",
        task_detail: dict | None = None,
    ) -> dict:
        """满足关闭条件后自动执行 task_close（done→closed）+ **读回确认**。

        满足关闭条件后自动执行 close + 读回确认。条件不满足则暂缓并记录原因。失败入待写队列重试。
        """
        detail = task_detail if task_detail is not None else self.get_task(task_id)
        ok, reason = self.can_close(
            task_detail=detail,
            verifier_passed=verifier_passed,
            deliverables_ok=deliverables_ok,
            records_ok=records_ok,
        )
        if not ok:
            return self.close_deferred(task_id=task_id, project_key=project_key, reason=reason)

        payload = {"comment": comment, "verifier_passed": verifier_passed,
                   "deliverables_ok": deliverables_ok, "records_ok": records_ok,
                   "before": str(detail.get("status") or "").lower()}

        if self.dry_run:
            self._log(f"[dry-run] task_close task={task_id}")
            return {"ok": True, "dry_run": True, "payload": payload}

        try:
            out = self._run_zt(
                ["close", "--task", str(task_id), "--comment", comment, "--exec-id", exec_id or ""],
                timeout=120,
            )
        except Exception as e:
            self._enqueue(task_id, project_key, "close", payload, str(e))
            raise ZenTaoWriteError(f"task_close 失败（已存待写队列）: {e}")

        # **读回确认**：必须核实 status 已变 closed
        try:
            after = self.get_task(task_id)
        except Exception as e:
            self._enqueue(task_id, project_key, "close", payload, f"读回失败: {e}")
            return {"ok": False, "reason": f"close 已调用但读回失败: {e}", "stage": "readback"}

        status = str(after.get("status", "")).lower()
        confirmed = status == "closed"
        result = {
            "ok": confirmed,
            "status_after": status,
            "confirmed": confirmed,
            "output_tail": out[-200:],
            "payload": payload,
        }
        if not confirmed:
            self._log(f"⚠ task_close 后读回 status={status}（期望 closed）")
        return result

    def close_deferred(self, *, task_id: str, project_key: str = "", reason: str = "") -> dict:
        """关闭条件不满足 → 暂缓关闭并记录具体原因（不视为失败，不伪造成功）。"""
        self._log(f"暂缓关闭 task={task_id}: {reason}")
        return {
            "ok": False,
            "deferred": True,
            "reason": reason or "关闭条件未满足",
            "note": f"任务 {task_id} 暂缓关闭，条件满足后可重试",
        }

    # ------------------------------------------------------- 内部
    def _run_zt(self, args: list[str], timeout: int = 90) -> str:
        if not os.path.exists(ZT_SCRIPT):
            raise ZenTaoWriteError(f"禅道适配器不存在: {ZT_SCRIPT}")
        try:
            p = subprocess.run(
                [sys.executable, "-I", ZT_SCRIPT, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            )
        except subprocess.TimeoutExpired:
            raise ZenTaoWriteError(f"禅道调用超时 {timeout}s")
        if p.returncode != 0:
            raise ZenTaoWriteError(f"禅道调用失败 rc={p.returncode}: {(p.stderr or p.stdout)[:200]}")
        return p.stdout or ""

    def _enqueue(self, task_id: str, project_key: str, action: str, payload: dict, error: str) -> None:
        if self.state:
            self.state.enqueue_pending_write(project_key, task_id, action, payload)
            self._log(f"已存待写队列: task={task_id} action={action} err={error[:80]}")

    def flush_pending(self, task_id: str | None = None) -> dict:
        """重试待写队列。避免重复追加相同记录（用 stage 标记幂等）；
        finish/close 由 zt.py 层幂等（已 done/closed 跳过），不产生重复流转。"""
        if not self.state:
            return {"flushed": 0, "note": "no state manager"}
        items = self.state.get_pending_writes(task_id)
        ok = fail = 0
        for w in items:
            payload = w.get("payload") or {}
            action = str(w.get("action") or "progress")
            try:
                if action == "finish":
                    self.finish(
                        task_id=w["task_id"],
                        project_key=w.get("project_key", ""),
                        verifier_passed=bool(payload.get("verifier_passed", True)),
                        consumed=payload.get("consumed"),
                        left=payload.get("left"),
                        finished_date=payload.get("finished_date"),
                        real_started=payload.get("real_started"),
                        summary=payload.get("summary", ""),
                        commit=payload.get("commit", ""),
                        exec_id=str(payload.get("exec_id") or ""),
                    )
                elif action == "close":
                    self.close(
                        task_id=w["task_id"],
                        project_key=w.get("project_key", ""),
                        comment=payload.get("comment", ""),
                        verifier_passed=bool(payload.get("verifier_passed", True)),
                        deliverables_ok=bool(payload.get("deliverables_ok", True)),
                        records_ok=bool(payload.get("records_ok", True)),
                        exec_id=str(payload.get("exec_id") or ""),
                    )
                elif action == "worklog":
                    self.report_worklog(
                        task_id=w["task_id"],
                        project_key=w.get("project_key", ""),
                        stage=payload.get("stage", "retry"),
                        progress=payload.get("progress"),
                        work=payload.get("work", ""),
                        date=payload.get("date", ""),
                        total_hours=payload.get("total_hours"),
                    )
                else:
                    self.report_progress(
                        task_id=w["task_id"],
                        project_key=w.get("project_key", ""),
                        stage=payload.get("stage", "retry"),
                        text=payload.get("text", ""),
                        attempt=int(w.get("attempts", 0)) + 1,
                    )
                self.state.mark_write_done(w["id"])
                ok += 1
            except Exception as e:
                self.state.mark_write_failed(w["id"], str(e))
                fail += 1
        return {"flushed": ok, "failed": fail, "remaining": len(items) - ok - fail}