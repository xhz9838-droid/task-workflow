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


class DingTalkDirectSender:
    """钉钉官方机器人 API 直发（/v1.0/robot/oToMessages/batchSend）。

    与 cc-connect 使用同一个钉钉机器人应用（robotCode=appKey）。
    实测背景：cc-connect v1.5.0 的 `send` 出站投递虚报成功不送达，
    而同一凭据直发官方 API 可靠送达，因此直发优先、cc-connect 兜底。
    凭据只存内存，不打印、不落盘。来源优先级：
        环境变量 DINGTALK_APP_KEY/SECRET → ~/.dingtalk-skills/config
        → cc-connect config.toml（client_id/client_secret）
    """

    TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
    SEND_URL = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"

    def __init__(self, cfg: HitlConfig, *, logger=None):
        self.cfg = cfg
        self._log = logger or (lambda m: None)
        self._token = ""
        self._token_expires = 0.0

    def _creds(self) -> tuple[str, str]:
        key = os.environ.get("DINGTALK_APP_KEY", "")
        sec = os.environ.get("DINGTALK_APP_SECRET", "")
        if key and sec:
            return key, sec
        p = os.path.join(os.path.expanduser("~"), ".dingtalk-skills", "config")
        if os.path.exists(p):
            kv = {}
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if "=" in line and not line.lstrip().startswith("#"):
                        k, _, v = line.partition("=")
                        kv[k.strip()] = v.strip()
            if kv.get("DINGTALK_APP_KEY") and kv.get("DINGTALK_APP_SECRET"):
                return kv["DINGTALK_APP_KEY"], kv["DINGTALK_APP_SECRET"]
        try:
            import tomllib

            for base in (os.environ.get("CC_CONNECT_DATA_DIR") or "",
                         os.path.join(os.path.expanduser("~"), ".cc-connect")):
                path = os.path.join(base or ".", "config.toml")
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        data = tomllib.load(f)
                    for proj in data.get("projects") or []:
                        for pf in proj.get("platforms") or []:
                            if pf.get("type") == "dingtalk":
                                opt = pf.get("options") or {}
                                if opt.get("client_id") and opt.get("client_secret"):
                                    return str(opt["client_id"]), str(opt["client_secret"])
        except Exception:
            pass
        raise NotifyError("未找到钉钉凭据（DINGTALK_APP_KEY/SECRET 或 cc-connect config）")

    def _access_token(self) -> str:
        import time as _t
        import json as _j
        import urllib.request

        if self._token and _t.time() < self._token_expires:
            return self._token
        key, sec = self._creds()
        body = _j.dumps({"appKey": key, "appSecret": sec}).encode("utf-8")
        req = urllib.request.Request(self.TOKEN_URL, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = _j.loads(r.read().decode("utf-8"))
        except Exception as e:
            raise NotifyError(f"获取钉钉 accessToken 失败: {e}")
        tok = data.get("accessToken") or ""
        if not tok:
            raise NotifyError(f"钉钉 accessToken 为空: {str(data)[:120]}")
        self._token = tok
        self._token_expires = _t.time() + 7000
        return tok

    def send(self, text: str, user_id: str) -> None:
        import json as _j
        import urllib.request

        key, _ = self._creds()
        tok = self._access_token()
        body = _j.dumps({
            "robotCode": key,
            "userIds": [user_id],
            "msgKey": "sampleText",
            "msgParam": _j.dumps({"content": text}, ensure_ascii=False),
        }).encode("utf-8")
        req = urllib.request.Request(self.SEND_URL, data=body, headers={
            "Content-Type": "application/json",
            "x-acs-dingtalk-access-token": tok,
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                resp = _j.loads(r.read().decode("utf-8") or "{}")
        except Exception as e:
            raise NotifyError(f"钉钉直发失败: {e}")
        invalid = resp.get("invalidStaffIdList") or []
        if invalid:
            raise NotifyError(f"钉钉直发用户无效: {invalid}")


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
    """钉钉通知。通道按 cfg.notify_transport 顺序尝试（默认直发优先、cc-connect 兜底）。
    dry_run=True 时只生成消息不发送（测试用）。"""

    def __init__(self, cfg: HitlConfig, *, logger=None):
        self.cfg = cfg
        self._log = logger or (lambda m: None)
        self._direct = DingTalkDirectSender(cfg, logger=logger)

    def _target_user(self, cc_session_key: str) -> str:
        if self.cfg.dingtalk_user_id:
            return self.cfg.dingtalk_user_id
        key = cc_session_key or os.environ.get("CC_SESSION_KEY", "")
        parts = (key or "").split(":")
        if len(parts) >= 2 and parts[1] == "d":
            return parts[-1]
        return os.environ.get("DINGTALK_USER_ID", "")

    def _send(self, body: str, *, cc_project: str = "", cc_session_key: str = "") -> None:
        if self.cfg.dry_run_notify:
            self._log(f"[dry-run] 通知: {body[:60]}...")
            return
        errors = []
        for transport in self.cfg.notify_transport:
            if transport == "dingtalk_direct":
                uid = self._target_user(cc_session_key)
                if not uid:
                    errors.append("direct: 无法解析目标用户 ID")
                    continue
                try:
                    self._direct.send(body, uid)
                    return
                except NotifyError as e:
                    errors.append(str(e))
            elif transport == "cc_connect":
                try:
                    self._send_ccconnect(body, cc_project, cc_session_key)
                    return
                except NotifyError as e:
                    errors.append(str(e))
        raise NotifyError("；".join(errors) or "无可用通知通道")

    def _send_ccconnect(self, body: str, cc_project: str = "", cc_session_key: str = "") -> None:
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
