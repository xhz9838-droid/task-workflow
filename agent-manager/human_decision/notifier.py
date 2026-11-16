# -*- coding: utf-8 -*-
"""HITL — 钉钉决策通知（复用 cc-connect，不新建通信系统）。

发送通道：`cc-connect send --stdin`（与 scripts/notify.sh 相同机制）。
会话绑定：CC_PROJECT / CC_SESSION_KEY（cc-connect 注入 agent 环境）
          → 决策记录 cc_project/cc_session_key
          → 回退"第一个活跃会话"。

通知失败：按配置重试；仍失败 → 记 NOTIFY_FAILED，决策继续等待，
**不允许 Agent 越过决策点**（阻塞由 Decision Manager 保证）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from human_decision.hitl_config import HitlConfig, resolve_cc_connect_bin  # noqa: E402
from human_decision.models import DecisionRecord  # noqa: E402


class NotifyError(Exception):
    pass


def build_decision_message(rec: DecisionRecord) -> str:
    lines = [
        "【Agent 重大决策请求】",
        "",
        f"禅道任务：#{rec.task_id}" + (f"（项目 {rec.project_key}）" if rec.project_key else ""),
        f"决策编号：{rec.decision_id}",
        f"决策等级：{rec.level.value}",
        "",
        "问题：",
        rec.question or "（无）",
    ]
    if rec.background:
        lines += ["", "背景：", rec.background]
    if rec.options:
        lines.append("")
        for opt in rec.options:
            lines.append(f"{opt.id}：{opt.description}")
    if rec.recommended_option:
        lines += ["", f"Agent 推荐：{rec.recommended_option}。"]
    if rec.recommend_reason:
        lines += ["推荐原因：", rec.recommend_reason]
    if rec.risk:
        lines += ["", "风险提示：", rec.risk]

    lines += ["", "请回复："]
    for opt in rec.options:
        lines.append(f"{opt.id}：选择 {opt.id}")
    if rec.options:
        lines.append("C + 自定义意见")
    else:
        lines.append("直接回复你的决策意见")
    lines.append("STOP：暂停当前任务")
    if not rec.options:
        pass
    lines += [
        "",
        f"（决策编号 {rec.decision_id}，可回复：{rec.decision_id} <你的选择>）",
    ]
    return "\n".join(lines)


def build_resume_message(rec: DecisionRecord) -> str:
    choice = rec.reply_choice or (rec.reply_kind.value if rec.reply_kind else "-")
    lines = [
        "【人工决策已返回】",
        "",
        f"Decision ID: {rec.decision_id}",
        "",
        f"用户选择：{choice}",
    ]
    if rec.reply_comment:
        lines += ["", "用户意见：", rec.reply_comment]
    lines += [
        "",
        "请基于此决策继续执行原任务。",
        "要求：",
        "1. 不要重新开始整个任务。",
        "2. 保留之前的执行上下文。",
        "3. 根据用户决策调整当前实施方案。",
        "4. 继续执行剩余步骤。",
        "5. 完成后运行测试。",
        "6. 最终报告任务执行结果。",
    ]
    return "\n".join(lines)


class DingTalkNotifier:
    """cc-connect send 封装。dry_run=True 时只生成消息不发送（测试用）。"""

    def __init__(self, cfg: HitlConfig, *, logger=None):
        self.cfg = cfg
        self._log = logger or (lambda m: None)

    def _send(self, body: str, *, cc_project: str = "", cc_session_key: str = "") -> None:
        if self.cfg.dry_run_notify:
            self._log(f"[dry-run] 通知: {body[:60]}...")
            return
        bin_ = resolve_cc_connect_bin(self.cfg.cc_connect_bin)
        args = [bin_, "send", "--stdin"]
        if cc_project:
            args += ["-p", cc_project]
        if cc_session_key:
            args += ["-s", cc_session_key]
        try:
            p = subprocess.run(
                args, input=body, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=60,
            )
            if p.returncode != 0:
                raise NotifyError(f"cc-connect send rc={p.returncode}: {(p.stderr or p.stdout)[:200]}")
        except FileNotFoundError as e:
            raise NotifyError(f"cc-connect 不存在（{bin_}）: {e}")
        except subprocess.TimeoutExpired:
            raise NotifyError("cc-connect send 超时(60s)")

    def _resolve_session(self, rec: DecisionRecord) -> tuple[str, str]:
        proj = rec.cc_project or os.environ.get("CC_PROJECT", "")
        key = rec.cc_session_key or os.environ.get("CC_SESSION_KEY", "")
        return proj, key

    def send_decision_request(self, rec: DecisionRecord) -> dict:
        """发送决策请求通知。返回 {sent, attempts, error}。"""
        body = build_decision_message(rec)
        proj, key = self._resolve_session(rec)
        last_err = ""
        for attempt in range(1, self.cfg.notify_retries + 1):
            try:
                self._send(body, cc_project=proj, cc_session_key=key)
                return {"sent": True, "attempts": attempt, "error": ""}
            except NotifyError as e:
                last_err = str(e)
                self._log(f"决策通知失败（第 {attempt} 次）: {e}")
                if attempt < self.cfg.notify_retries:
                    time.sleep(self.cfg.notify_retry_interval_seconds)
        return {"sent": False, "attempts": self.cfg.notify_retries, "error": last_err}

    def send_text(self, body: str, *, cc_project: str = "", cc_session_key: str = "") -> dict:
        try:
            self._send(body, cc_project=cc_project, cc_session_key=cc_session_key)
            return {"sent": True, "error": ""}
        except NotifyError as e:
            return {"sent": False, "error": str(e)}

    def send_reminder(self, rec: DecisionRecord) -> dict:
        body = (
            "【决策提醒】\n"
            f"决策编号：{rec.decision_id}\n"
            f"禅道任务：#{rec.task_id}\n"
            f"问题：{rec.question}\n"
            "该决策仍在等待回复。请回复选项（如 A）或 STOP 暂停任务。"
        )
        return self.send_text(body)

    def send_timeout_notice(self, rec: DecisionRecord) -> dict:
        body = (
            "【决策超时】\n"
            f"决策编号：{rec.decision_id}\n"
            f"禅道任务：#{rec.task_id}\n"
            "长时间未收到回复，任务保持暂停。**不会自动批准任何方案**。\n"
            "你仍可随时回复选项（如 A）继续，或回复 STOP 暂停任务。"
        )
        return self.send_text(body)
