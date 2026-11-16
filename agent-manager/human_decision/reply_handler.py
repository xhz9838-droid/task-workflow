# -*- coding: utf-8 -*-
"""HITL — 用户回复处理（钉钉回复 → 决策库）。

回复来源（可并存，幂等去重）：
    hook  — cc-connect `message.received` 钩子（command/http），带权威身份
            CC_HOOK_USER_ID / CC_HOOK_USER_NAME / CC_HOOK_SESSION_KEY /
            CC_HOOK_CONTENT / CC_HOOK_PROJECT / CC_HOOK_TIMESTAMP
    watch — 轮询 cc-connect 会话文件（~/.cc-connect/sessions/*.json），
            零配置兜底；单聊可从会话键解析用户 ID，群聊无法验证身份（默认拒绝）
    cli   — 运维手动注入（测试/补录）

处理步骤（每条回复）：
    1. 解析 DEC-ID / 选项 / STOP / 自定义意见
    2. 绑定决策（DEC-ID 显式 > 绑定会话内唯一待决 > 无法绑定则忽略/提示）
    3. 验证发送人身份（白名单）
    4. 验证决策仍可回复（幂等：一决策仅一次有效回复）
    5. 保存回复、更新决策状态
    6. 通知 Session Resumer 恢复执行
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from human_decision.hitl_config import HitlConfig  # noqa: E402
from human_decision.models import (  # noqa: E402
    DecisionRecord,
    DecisionStatus,
    ParsedReply,
    ReplyKind,
    ReplyRecord,
    _now,
)
from human_decision.reply_parser import parse_reply  # noqa: E402


def _fingerprint(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8", "replace")).hexdigest()[:24]


class ReplyHandler:
    def __init__(self, cfg: HitlConfig, store, resumer=None, notifier=None, *, logger=None):
        self.cfg = cfg
        self.store = store
        self.resumer = resumer
        self.notifier = notifier
        self._log = logger or (lambda m: None)

    # ------------------------------------------------------- 主入口
    def handle(
        self,
        *,
        raw_text: str,
        source: str,
        user_id: str = "",
        user_name: str = "",
        msg_id: str = "",
        chat_session_key: str = "",
        chat_scope: str = "",
        msg_ts: str = "",
    ) -> dict:
        """处理一条用户回复。返回 {outcome, decision_id, reason}。

        outcome: accepted | duplicate | rejected | unmatched | invalid
        """
        text = (raw_text or "").strip()
        if not text:
            return {"outcome": "unmatched", "reason": "空消息"}

        parsed = parse_reply(text)
        decision = self._resolve_decision(parsed.decision_id, chat_session_key)
        if decision is None:
            if parsed.decision_id:
                return {"outcome": "unmatched", "decision_id": parsed.decision_id,
                        "reason": f"未找到决策 {parsed.decision_id}"}
            return {"outcome": "unmatched", "reason": "当前没有匹配的待决决策"}

        # 防旧消息误伤：watch 来源只接受决策创建之后的消息（时间容差 60s）
        if source == "watch" and msg_ts and decision.created_at:
            if _norm_ts(msg_ts) < _shift_ts(decision.created_at, -60):
                return {"outcome": "unmatched", "decision_id": decision.decision_id,
                        "reason": "消息早于决策创建时间，忽略"}

        # 带上方案选项重新解析（判定无效选项）
        parsed = parse_reply(text, [o.id for o in decision.options])

        # 身份校验
        auth_reason = self._check_identity(source, user_id, chat_session_key, chat_scope)
        if auth_reason:
            self._reject(decision, text, source, user_id, user_name, msg_id,
                         parsed, f"身份校验失败: {auth_reason}")
            self._maybe_reply_user(decision, f"你没有该决策的审批权限（决策 {decision.decision_id}）。")
            return {"outcome": "rejected", "decision_id": decision.decision_id,
                    "reason": f"身份校验失败: {auth_reason}"}

        if not parsed.valid:
            self._reject(decision, text, source, user_id, user_name, msg_id,
                         parsed, parsed.invalid_reason)
            self._maybe_reply_user(
                decision,
                f"无法识别的回复：{parsed.invalid_reason}。请回复选项（如 A）或 STOP（决策 {decision.decision_id}）。",
            )
            return {"outcome": "invalid", "decision_id": decision.decision_id,
                    "reason": parsed.invalid_reason}

        if not decision.is_replyable:
            self.store.record_reply(ReplyRecord(
                decision_id=decision.decision_id, raw_text=text, source=source,
                accepted=False, reject_reason=f"决策状态 {decision.status.value} 不可回复",
                reply_user_id=user_id, reply_user_name=user_name, msg_id=msg_id,
                kind=parsed.kind,
            ))
            return {"outcome": "duplicate", "decision_id": decision.decision_id,
                    "reason": f"决策已处理（{decision.status.value}）"}

        rep = ReplyRecord(
            decision_id=decision.decision_id, raw_text=text, source=source,
            accepted=True, reply_user_id=user_id, reply_user_name=user_name,
            msg_id=msg_id, parsed_choice=parsed.choice, parsed_comment=parsed.comment,
            kind=parsed.kind,
        )
        rid = self.store.record_reply(rep)
        if rid is None:
            return {"outcome": "duplicate", "decision_id": decision.decision_id,
                    "reason": "重复消息（msg_id 已处理）"}

        # 状态转移（原子守卫保证只生效一次）
        if parsed.kind == ReplyKind.STOP:
            ok = self.store.transition(
                decision.decision_id, DecisionStatus.REJECTED,
                allowed_from=self._replyable_states(),
                fields={
                    "user_reply": text, "reply_kind": parsed.kind,
                    "reply_comment": parsed.comment, "reply_user_id": user_id,
                    "reply_user_name": user_name, "replied_at": _now(),
                },
            )
            if not ok:
                return {"outcome": "duplicate", "decision_id": decision.decision_id,
                        "reason": "并发重复处理"}
            self.store.log_event(decision.decision_id, "user_stop", {"user": user_name or user_id})
            self._maybe_reply_user(decision, f"已暂停任务（决策 {decision.decision_id}）。")
            return {"outcome": "accepted", "decision_id": decision.decision_id, "choice": "STOP"}

        ok = self.store.transition(
            decision.decision_id, DecisionStatus.DECISION_RECEIVED,
            allowed_from=self._replyable_states(),
            fields={
                "user_reply": text, "reply_kind": parsed.kind,
                "reply_choice": parsed.choice, "reply_comment": parsed.comment,
                "reply_user_id": user_id, "reply_user_name": user_name,
                "replied_at": _now(),
            },
        )
        if not ok:
            return {"outcome": "duplicate", "decision_id": decision.decision_id,
                    "reason": "并发重复处理"}

        self._maybe_reply_user(
            decision,
            f"已收到你的决策（{decision.decision_id}）：{parsed.choice or parsed.comment or text}。正在恢复执行…",
        )

        # 恢复原 Session
        if self.resumer is not None:
            try:
                self.resumer.resume(self.store.get(decision.decision_id))
            except Exception as e:
                self.store.log_event(decision.decision_id, "resume_error", {"error": str(e)[:200]})
                self.store.transition(decision.decision_id, DecisionStatus.RESUME_FAILED,
                                      allowed_from={DecisionStatus.DECISION_RECEIVED,
                                                    DecisionStatus.RESUMING},
                                      fields={"last_error": str(e)[:300]})

        return {"outcome": "accepted", "decision_id": decision.decision_id,
                "choice": parsed.choice, "comment": parsed.comment}

    # ------------------------------------------------------- 决策绑定
    def _resolve_decision(self, dec_id: Optional[str], chat_session_key: str) -> Optional[DecisionRecord]:
        if dec_id:
            return self.store.get(dec_id)
        waiting = self.store.list_waiting()
        if chat_session_key:
            bound = [d for d in waiting if d.cc_session_key == chat_session_key]
            if len(bound) == 1:
                return bound[0]
            if len(bound) > 1:
                return None  # 歧义：要求显式 DEC-ID（由调用方回执提示）
            # 无待决 → 找该会话最近已决决策，用于「重复回复」提示（不串新任务）
            decided = [d for d in self.store.list(limit=50)
                       if d.cc_session_key == chat_session_key and not d.is_waiting]
            if decided:
                return decided[0]  # store.list 按 created_at 倒序
            return None
        # 无会话键（cli/测试）：全局唯一待决才允许
        if len(waiting) == 1:
            return waiting[0]
        decided = self.store.list(limit=1)
        return decided[0] if decided else None

    def ambiguous_decisions(self, chat_session_key: str = "") -> list[DecisionRecord]:
        waiting = self.store.list_waiting()
        if chat_session_key:
            waiting = [d for d in waiting if d.cc_session_key == chat_session_key]
        return waiting

    # ------------------------------------------------------- 身份
    def _check_identity(self, source: str, user_id: str, chat_session_key: str, chat_scope: str) -> str:
        """返回非空字符串 = 校验失败原因。"""
        if user_id and user_id in self.cfg.decider_ids():
            return ""
        scope = chat_scope or _chat_scope(chat_session_key)
        if source in ("cli", "test"):
            return "" if not self.cfg.deciders else (
                "" if not user_id else f"用户 {user_id} 不在授权决策人白名单"
            )
        if self.cfg.is_authorized(user_id, chat_scope=scope):
            return ""
        if not user_id and scope.startswith("g"):
            return "群聊回复无法验证发送人身份（建议配置 cc-connect message.received hook）"
        return f"用户 {user_id or '未知'} 不在授权决策人白名单"

    def _replyable_states(self):
        from human_decision.models import REPLYABLE

        return set(REPLYABLE)

    # ------------------------------------------------------- 记录
    def _reject(self, decision, text, source, user_id, user_name, msg_id,
                parsed: ParsedReply, reason: str) -> None:
        self.store.record_reply(ReplyRecord(
            decision_id=decision.decision_id, raw_text=text, source=source,
            accepted=False, reject_reason=reason[:200],
            reply_user_id=user_id, reply_user_name=user_name, msg_id=msg_id,
            kind=parsed.kind,
        ))

    def _maybe_reply_user(self, decision: DecisionRecord, text: str) -> None:
        """回执提示（尽力而为，失败不影响决策处理）。"""
        if self.notifier is None:
            return
        try:
            self.notifier.send_text(
                text, cc_project=decision.cc_project,
                cc_session_key=decision.cc_session_key,
            )
        except Exception as e:
            self._log(f"回执失败: {e}")

    # ------------------------------------------------------- 来源：hook
    def handle_hook_env(self, env: dict | None = None) -> dict:
        """cc-connect command hook 入口：从 CC_HOOK_* 环境变量读取。"""
        env = env or dict(os.environ)
        event = env.get("CC_HOOK_EVENT", "")
        if event and event != "message.received":
            return {"outcome": "unmatched", "reason": f"非 message.received 事件: {event}"}
        return self.handle(
            raw_text=env.get("CC_HOOK_CONTENT", ""),
            source="hook",
            user_id=env.get("CC_HOOK_USER_ID", ""),
            user_name=env.get("CC_HOOK_USER_NAME", ""),
            chat_session_key=env.get("CC_HOOK_SESSION_KEY", ""),
            chat_scope=_chat_scope(env.get("CC_HOOK_SESSION_KEY", "")),
            msg_id=_fingerprint(
                env.get("CC_HOOK_USER_ID", ""), env.get("CC_HOOK_TIMESTAMP", ""),
                env.get("CC_HOOK_CONTENT", ""),
            ),
        )

    def handle_hook_payload(self, payload: dict) -> dict:
        """cc-connect http hook / bridge 事件入口。"""
        return self.handle(
            raw_text=payload.get("content") or payload.get("message", ""),
            source="hook",
            user_id=str(payload.get("user_id") or payload.get("sender_id") or ""),
            user_name=str(payload.get("user_name") or ""),
            chat_session_key=str(payload.get("session_key") or ""),
            chat_scope=_chat_scope(str(payload.get("session_key") or "")),
            msg_id=str(payload.get("msg_id") or _fingerprint(
                str(payload.get("user_id", "")), str(payload.get("timestamp", "")),
                str(payload.get("content", "")),
            )),
        )

    # ------------------------------------------------------- 来源：watch
    def collect_from_session_files(self) -> list[dict]:
        """轮询 cc-connect 会话文件，处理新增用户消息。返回处理结果列表。"""
        results = []
        sessions_dir = self.cfg.sessions_dir()
        if not os.path.isdir(sessions_dir):
            return results
        for name in sorted(os.listdir(sessions_dir)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(sessions_dir, name)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            chat_key, chat_map = _chat_key_of(data)
            for sid, sess in (data.get("sessions") or {}).items():
                history = sess.get("history") or []
                for idx, msg in enumerate(history):
                    if msg.get("role") != "user":
                        continue
                    ts = str(msg.get("timestamp") or "")
                    content = str(msg.get("content") or "")
                    msg_id = _fingerprint(name, sid, ts, content)
                    if not self._mark_seen(msg_id):
                        continue
                    user_id, user_name = _user_of_chat(chat_key, data)
                    r = self.handle(
                        raw_text=content, source="watch",
                        user_id=user_id, user_name=user_name,
                        chat_session_key=chat_key,
                        chat_scope=_chat_scope(chat_key),
                        msg_id=msg_id, msg_ts=ts,
                    )
                    results.append(r)
        return results

    # 会话文件消息去重（避免重复扫描重复处理）
    _seen_cache: set = set()

    def _mark_seen(self, msg_id: str) -> bool:
        """返回 True 表示新消息（未处理过）。"""
        if msg_id in ReplyHandler._seen_cache:
            return False
        # 持久去重：decision_replies.msg_id 全局查重
        with self.store._lock:
            row = self.store._conn.execute(
                "SELECT id FROM decision_replies WHERE msg_id=?", (msg_id,)
            ).fetchone()
        if row:
            ReplyHandler._seen_cache.add(msg_id)
            return False
        ReplyHandler._seen_cache.add(msg_id)
        return True


def _parse_ts(ts: str) -> Optional["datetime.datetime"]:
    """解析 ISO 时间（兼容 7 位小数秒）。失败返回 None。"""
    import datetime as _dt

    ts = (ts or "").strip()
    if not ts:
        return None
    if "." in ts:
        head, _, tail = ts.partition(".")
        frac = ""
        rest = tail
        for i, ch in enumerate(tail):
            if ch.isdigit():
                frac += ch
            else:
                rest = tail[i:]
                break
        ts = head + "." + (frac + "000000")[:6] + rest
    try:
        return _dt.datetime.fromisoformat(ts)
    except Exception:
        return None


def _shift_ts(ts: str, seconds: int) -> str:
    """时间平移后返回可字符串比较的 ISO 归一格式；解析失败原样返回。"""
    import datetime as _dt

    d = _parse_ts(ts)
    if d is None:
        return ts
    return (d + _dt.timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _norm_ts(ts: str) -> str:
    d = _parse_ts(ts)
    return d.isoformat(timespec="seconds") if d else (ts or "")


def _chat_scope(chat_key: str) -> str:
    """dingtalk:d:cid:uid → d；dingtalk:g:... → g。"""
    parts = (chat_key or "").split(":")
    return parts[1] if len(parts) >= 2 else ""


def _chat_key_of(data: dict) -> tuple[str, dict]:
    """取会话文件绑定的聊天键（active_session 的第一个 key）。"""
    active = data.get("active_session") or {}
    for k in active:
        return k, data
    um = data.get("user_meta") or {}
    for k in um:
        return k, data
    return "", data


def _user_of_chat(chat_key: str, data: dict) -> tuple[str, str]:
    """单聊：从会话键尾段取用户 ID；群聊：user_meta 可能有昵称，ID 不可得。"""
    meta = (data.get("user_meta") or {}).get(chat_key) or {}
    name = str(meta.get("user_name") or "")
    scope = _chat_scope(chat_key)
    if scope == "d":
        uid = chat_key.rsplit(":", 1)[-1] if chat_key else ""
        return uid, name
    return "", name
