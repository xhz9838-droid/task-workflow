# -*- coding: utf-8 -*-
"""HITL — Session Resumer：把用户决策送回原 Claude Session。

恢复策略优先级（不得把"重启空白 Agent"伪装成恢复）：
  1. live_continue      原 Session 仍存活：
                          a) 阻塞中的 MCP 工具仍在轮询决策库 → 工具直接取回（无需注入）
                          b) 回合已结束但 cc-connect 会话 live → Management API /send 注入决策结果
  2. cc_connect_resume  原 Session 已退出：cc-connect 保留 agent_session_id，
                        用户下一条消息即 `--resume` 原会话（原生机制）；
                        此处核验 agent_session_id 可用，并把决策结果写入检查点供 Agent 取回。
  3. checkpoint_rebuild 以上都不可用：生成检查点包（任务/进度/已完成/未完成/决策/文件），
                        明确标注 resume_method=checkpoint_rebuild。

无论走哪条路径，都在 execution/{project}/{task}/human-decision/ 留下
resume-packet.md（审计 + 重建素材），并如实记录 resume_method。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))  # task-workflow/
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from human_decision.hitl_config import HitlConfig, resolve_cc_connect_bin  # noqa: E402
from human_decision.models import (  # noqa: E402
    DecisionRecord,
    DecisionStatus,
    ResumeMethod,
    _now,
)
from human_decision.notifier import build_resume_message  # noqa: E402


class SessionResumer:
    def __init__(self, cfg: HitlConfig, store, *, logger=None):
        self.cfg = cfg
        self.store = store
        self._log = logger or (lambda m: None)

    # ------------------------------------------------------- 对外入口
    def _tool_suspended(self, decision_id: str) -> bool:
        """阻塞工具是否已超时挂起（最后一次 tool_waiting 之后出现过 tool_suspended）。"""
        suspended = False
        for ev in self.store.events(decision_id):
            if ev.get("event") == "tool_waiting":
                suspended = False
            elif ev.get("event") == "tool_suspended":
                suspended = True
        return suspended

    def resume(self, rec: DecisionRecord) -> dict:
        """按优先级尝试恢复。返回 {resume_method, detail}。"""
        tool_suspended = self._tool_suspended(rec.decision_id)
        packet_path = self.write_resume_packet(rec)

        method: ResumeMethod
        detail = ""

        if not tool_suspended:
            # 阻塞中的工具仍在等待 → 工具自取回，原进程原地继续（最强恢复）
            method = ResumeMethod.LIVE_CONTINUE
            detail = "blocked tool polling decision store (live continuation)"
        else:
            injected = self._try_live_inject(rec)
            if injected:
                method = ResumeMethod.LIVE_CONTINUE
                detail = "decision injected via cc-connect management API (/send)"
            elif self._agent_sid_available(rec):
                method = ResumeMethod.CC_CONNECT_RESUME
                detail = (
                    "cc-connect preserved agent_session_id; the user's next message "
                    "resumes the original session (--resume). decision also written to "
                    f"checkpoint: {packet_path}"
                )
            else:
                method = ResumeMethod.CHECKPOINT_REBUILD
                detail = f"session not live and no agent_session_id; rebuild from checkpoint: {packet_path}"

        # 状态转移 RESUMING -> RESUMED
        ok = self.store.transition(
            rec.decision_id, DecisionStatus.RESUMING,
            allowed_from={DecisionStatus.DECISION_RECEIVED, DecisionStatus.RESUME_FAILED},
        )
        if not ok:
            # 已在 RESUMING/RESUMED（并发）——不重复
            self.store.log_event(rec.decision_id, "resume_skipped", {"reason": "already resuming"})
            cur = self.store.get(rec.decision_id)
            return {"resume_method": cur.resume_method.value if cur and cur.resume_method else method.value,
                    "detail": "already resumed/resuming"}

        self.store.transition(
            rec.decision_id, DecisionStatus.RESUMED,
            allowed_from={DecisionStatus.RESUMING},
            fields={"resumed_at": _now(), "resume_method": method},
        )
        self.store.log_event(rec.decision_id, "resumed", {"method": method.value, "detail": detail})
        return {"resume_method": method.value, "detail": detail}

    # ------------------------------------------------------- 检查点包
    def checkpoint_dir(self, rec: DecisionRecord) -> str:
        proj = rec.project_key or "_"
        root = self.cfg.execution_root or os.path.join(_ROOT, "execution")
        path = os.path.join(root, proj, rec.task_id, "human-decision")
        os.makedirs(path, exist_ok=True)
        return path

    def write_resume_packet(self, rec: DecisionRecord) -> str:
        """生成恢复素材包（任务上下文 + 决策 + 已有执行状态）。"""
        d = self.checkpoint_dir(rec)
        path = os.path.join(d, f"resume-packet-{rec.decision_id}.md")
        ctx = self._task_context(rec)
        lines = [
            f"# 恢复包 {rec.decision_id}",
            "",
            f"- task_id: {rec.task_id}",
            f"- project_key: {rec.project_key or '-'}",
            f"- 原 Session ID: {rec.session_id or '-'}",
            f"- cc-connect: project={rec.cc_project or '-'} session_key={rec.cc_session_key or '-'}",
            f"- 生成时间: {_now()}",
            "",
            "## 人工决策",
            f"- 等级: {rec.level.value}",
            f"- 问题: {rec.question}",
            f"- 背景: {rec.background or '-'}",
            f"- 用户选择: {rec.reply_choice or rec.reply_comment or '-'}",
            f"- 用户意见: {rec.reply_comment or '-'}",
            f"- 回复人: {rec.reply_user_name or rec.reply_user_id or '-'}",
            f"- 回复时间: {rec.replied_at or '-'}",
            "",
            "## 任务执行上下文",
            ctx,
            "",
            "## 恢复要求",
            "1. 不要重新开始整个任务。",
            "2. 基于上述上下文与决策继续执行剩余步骤。",
            "3. 若本文件存在但原 Session 已丢失，按本文件重建执行上下文，并在报告中注明 resume_method=checkpoint_rebuild。",
        ]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        # 同步写一份机器可读
        with open(os.path.join(d, f"decision-{rec.decision_id}.json"), "w", encoding="utf-8") as f:
            json.dump(rec.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    def _task_context(self, rec: DecisionRecord) -> str:
        parts = []
        proj = rec.project_key or ""
        root = self.cfg.execution_root or os.path.join(_ROOT, "execution")
        base = os.path.join(root, proj, rec.task_id) if proj else ""
        for name in ("task-context.md", "run-state.json", "progress.md"):
            p = os.path.join(base, name) if base else ""
            if p and os.path.exists(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        content = f.read()
                    if len(content) > 4000:
                        content = content[:4000] + "\n...(截断)"
                    parts.append(f"### {name}\n```\n{content}\n```")
                except Exception as e:
                    parts.append(f"### {name}\n(读取失败: {e})")
        return "\n\n".join(parts) or "（无执行状态文件——从原始任务描述与决策恢复）"

    # ------------------------------------------------------- live 注入
    def _try_live_inject(self, rec: DecisionRecord) -> bool:
        """Session live 时经 Management API POST /send 注入决策结果。"""
        if not rec.cc_project or not rec.cc_session_key:
            rec2 = self._fill_cc_binding(rec)
            if rec2:
                rec = rec2
        if not rec.cc_project or not rec.cc_session_key:
            return False
        if not self._session_live(rec.cc_project, rec.cc_session_key):
            return False
        body = {"session_key": rec.cc_session_key, "message": build_resume_message(rec)}
        try:
            self._mgmt_request("POST", f"/api/v1/projects/{rec.cc_project}/send", body)
            return True
        except Exception as e:
            self._log(f"live 注入失败: {e}")
            self.store.log_event(rec.decision_id, "live_inject_failed", {"error": str(e)[:200]})
            return False

    def _session_live(self, project: str, session_key: str) -> bool:
        try:
            data = self._mgmt_request("GET", f"/api/v1/projects/{project}/sessions")
        except Exception:
            return False
        sessions = (data or {}).get("sessions") or []
        for s in sessions:
            if s.get("session_key") == session_key and s.get("live"):
                return True
        # 无 session_key 字段匹配时保守返回 False
        return False

    def _agent_sid_available(self, rec: DecisionRecord) -> bool:
        if rec.session_id:
            return True
        sid = self._query_agent_sid(rec.cc_project or os.environ.get("CC_PROJECT", ""),
                                   rec.cc_session_key or os.environ.get("CC_SESSION_KEY", ""))
        if sid:
            self.store.update_fields(rec.decision_id, session_id=sid)
            rec.session_id = sid
            return True
        return False

    def _query_agent_sid(self, project: str, session_key: str) -> str:
        if not project or not session_key:
            return ""
        try:
            p = subprocess.run(
                [resolve_cc_connect_bin(self.cfg.cc_connect_bin), "agent-sid", "-p", project, "-s", session_key],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            )
            if p.returncode == 0:
                return (p.stdout or "").strip()
        except Exception:
            pass
        return ""

    def _fill_cc_binding(self, rec: DecisionRecord) -> Optional[DecisionRecord]:
        proj = os.environ.get("CC_PROJECT", "")
        key = os.environ.get("CC_SESSION_KEY", "")
        if proj or key:
            self.store.update_fields(
                rec.decision_id,
                **{"cc_project": rec.cc_project or proj, "cc_session_key": rec.cc_session_key or key},
            )
            rec.cc_project = rec.cc_project or proj
            rec.cc_session_key = rec.cc_session_key or key
            return rec
        return None

    # ------------------------------------------------------- Management API
    def _mgmt_request(self, method: str, path: str, body: dict | None = None):
        base = (self.cfg.management_api or "").rstrip("/")
        if not base:
            raise RuntimeError("management_api 未配置")
        url = base + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.cfg.management_token:
            req.add_header("Authorization", f"Bearer {self.cfg.management_token}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
        if isinstance(payload, dict) and payload.get("ok") is False:
            raise RuntimeError(payload.get("error", "management api error"))
        return payload.get("data", payload) if isinstance(payload, dict) else payload
