# -*- coding: utf-8 -*-
"""Claude Code UserPromptSubmit hook：HITL 决策消息分流。

目标：
    - 决策消息由 HITL Handler 处理，并阻止本轮普通 Agent 处理；
    - 普通聊天消息放行给 Agent；
    - 无法确定是否为决策消息时放行，不误伤普通聊天。

启用方式（需用户明确授权，默认不安装）：
    ~/.claude/settings.json 的 hooks.UserPromptSubmit 指向本脚本。
    cc-connect 启动的 Claude 会话会注入 CC_PROJECT / CC_SESSION_KEY。

退出码：
    2 = 已作为 HITL 处理，阻止普通 Agent（stderr 为提示）
    0 = 放行普通聊天
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_PARENT)
os.environ.setdefault("WORKFLOW_HOME", _ROOT)
for _p in (_PARENT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human_decision.decision_manager import DecisionManager  # noqa: E402
from human_decision.reply_parser import parse_reply  # noqa: E402

_STOP_WORDS = {"stop", "停止", "暂停", "终止", "abort"}
_NL_RE = ("选择", "选", "按", "采用", "同意", "接受")
_LOG = os.path.join(_ROOT, "agent-manager", "logs", "hitl-prompt-router.log")


def _log(event: dict) -> None:
    """最小观测：记录路由结果，不含完整用户文本。"""
    try:
        import datetime as _dt
        os.makedirs(os.path.dirname(_LOG), exist_ok=True)
        event = dict(event, ts=_dt.datetime.now().astimezone().isoformat(timespec="seconds"))
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _looks_like_hitl(prompt: str, option_ids: list) -> bool:
    text = (prompt or "").strip()
    if not text:
        return False
    if parse_reply(text).decision_id:
        return True
    parsed = parse_reply(text, option_ids)
    if parsed.valid:
        return True
    first = text.split()[0].lower() if text.split() else ""
    if first in _STOP_WORDS:
        return True
    if len(text.split()) == 1 and len(text) == 1 and text.isalpha():
        return True  # 单字母，可能是决策回复
    if any(k in text for k in _NL_RE):
        return True
    return False


def _recent_handled(mgr: DecisionManager, chat_session_key: str, prompt: str):
    """Daemon 可能先消费消息；Hook 仍需阻止同一消息再进 Agent。"""
    import datetime as _dt
    import time as _time
    now = _time.time()
    text = (prompt or "").strip()
    for d in mgr.store.list(limit=50):
        if d.cc_session_key != chat_session_key or d.is_waiting or not d.replied_at:
            continue
        try:
            ts = _dt.datetime.fromisoformat(d.replied_at).timestamp()
        except Exception:
            continue
        if now - ts > 300:
            continue
        if (d.user_reply or "").strip() == text:
            return d
    return None


def route_prompt(prompt: str, chat_session_key: str, user_id: str = "",
                 manager: DecisionManager | None = None, msg_id: str = "",
                 msg_ts: str = "") -> tuple[bool, str]:
    """返回 (block_agent, message)。只处理 HITL 决策消息。"""
    if not prompt or not chat_session_key:
        return False, ""
    mgr = manager or DecisionManager()
    waiting = mgr.store.list_waiting()
    candidates = [d for d in waiting if d.cc_session_key == chat_session_key]
    explicit = parse_reply(prompt).decision_id
    explicit_rec = mgr.store.get(explicit) if explicit else None
    option_ids = []
    for d in candidates:
        option_ids.extend(o.id for o in d.options)
    if explicit_rec is not None:
        option_ids.extend(o.id for o in explicit_rec.options)
    option_ids = sorted(set(option_ids))

    if not candidates and explicit_rec is None and not explicit:
        # daemon 可能已先接受同一消息：仍阻止 Agent，避免双通道
        recent = _recent_handled(mgr, chat_session_key, prompt)
        if recent is not None:
            _log({"event": "route", "block": True, "outcome": "already_handled",
                  "decision_id": recent.decision_id, "prompt_len": len(prompt)})
            return True, "决策已处理（%s），不再进入普通 Agent。" % recent.decision_id
        return False, ""
    if not _looks_like_hitl(prompt, option_ids):
        return False, ""

    scope = "d" if chat_session_key.split(":")[1:2] == ["d"] else ""
    if not msg_id:
        msg_id = hashlib.sha1(
            ("prompt-hook|%s|%s|%s" % (chat_session_key, msg_ts, prompt)).encode("utf-8", "replace")
        ).hexdigest()[:24]
    r = mgr.apply_reply(
        raw_text=prompt, source="hook", user_id=user_id,
        chat_session_key=chat_session_key, chat_scope=scope,
        msg_id=msg_id, msg_ts=msg_ts,
    )
    outcome = r.get("outcome", "")
    _log({"event": "route", "block": True, "outcome": outcome,
          "decision_id": r.get("decision_id"), "chat_hash": hashlib.sha1(
              chat_session_key.encode("utf-8", "replace")).hexdigest()[:12],
          "prompt_len": len(prompt), "candidates": len(candidates)})
    if outcome == "accepted":
        return True, "已收到决策（%s）：%s" % (r.get("decision_id"), r.get("choice") or "自定义意见")
    return True, "决策未处理：%s" % (r.get("reason") or outcome)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # 非 hook 输入，放行
    prompt = str(payload.get("prompt") or "")
    session_id = str(payload.get("session_id") or "")
    chat_key = os.environ.get("CC_SESSION_KEY", "")
    user_id = chat_key.rsplit(":", 1)[-1] if chat_key.startswith("dingtalk:d:") else ""
    _log({"event": "invoke", "has_cc_key": bool(chat_key),
          "prompt_len": len(prompt), "has_session": bool(session_id)})
    msg_id = hashlib.sha1(
        ("prompt-hook|%s|%s" % (session_id, prompt)).encode("utf-8", "replace")
    ).hexdigest()[:24]
    try:
        block, message = route_prompt(prompt, chat_key, user_id,
                                      msg_id=msg_id, msg_ts="")
    except Exception as e:  # noqa: BLE001 —— Hook 异常不得让普通聊天大面积不可用
        _log({"event": "hook_error", "error": "%s: %s" % (type(e).__name__, e)})
        return 0
    if block:
        sys.stderr.write(message + "\n")
        return 2
    _log({"event": "route", "block": False, "prompt_len": len(prompt),
          "chat_hash": hashlib.sha1(chat_key.encode("utf-8", "replace")).hexdigest()[:12]
          if chat_key else ""})
    return 0


if __name__ == "__main__":
    sys.exit(main())
