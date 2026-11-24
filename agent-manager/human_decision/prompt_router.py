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
for _p in (_PARENT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human_decision.decision_manager import DecisionManager  # noqa: E402
from human_decision.reply_parser import parse_reply  # noqa: E402

_STOP_WORDS = {"stop", "停止", "暂停", "终止", "abort"}
_NL_RE = ("选择", "选", "按", "采用", "同意", "接受")


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
    msg_id = hashlib.sha1(
        ("prompt-hook|%s|%s" % (session_id, prompt)).encode("utf-8", "replace")
    ).hexdigest()[:24]
    block, message = route_prompt(prompt, chat_key, user_id,
                                  msg_id=msg_id, msg_ts="")
    if block:
        sys.stderr.write(message + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
