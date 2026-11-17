# -*- coding: utf-8 -*-
"""HITL — 用户回复解析。

支持格式（通知消息中明示）：
    A              选择方案 A
    A 说明文字      选择方案 A 并附意见
    C 自定义意见    未定义为方案的字母视为「自定义意见」（等价方案 C）
    STOP / 停止 / 暂停   暂停当前任务
    DEC-3413-001 A  显式绑定决策编号（多决策并行时必须）

纯文本（非字母开头）→ 自定义意见（仅当决策唯一时可绑定，绑定在 reply_handler）。
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from human_decision.decision_detector import DEC_ID_RE, STOP_WORDS
from human_decision.models import ParsedReply, ReplyKind


def parse_reply(text: str, option_ids: Iterable[str] = ()) -> ParsedReply:
    raw = (text or "").strip()
    if not raw:
        return ParsedReply(None, ReplyKind.CUSTOM, valid=False, invalid_reason="空回复", raw_text=raw)

    # 1. 提取显式 DEC-ID
    decision_id: Optional[str] = None
    m = DEC_ID_RE.search(raw)
    if m:
        decision_id = m.group(1).upper()
        raw = (raw[: m.start()] + raw[m.end() :]).strip(" 　:：-")

    # 2. STOP
    first = raw.split()[0] if raw.split() else ""
    if raw.lower() in STOP_WORDS or first.lower() in STOP_WORDS:
        rest = raw[len(first):].strip() if first else ""
        return ParsedReply(decision_id, ReplyKind.STOP, comment=rest or None, raw_text=text.strip())

    if not raw:
        return ParsedReply(decision_id, ReplyKind.CUSTOM, valid=False,
                           invalid_reason="仅包含决策编号，没有回复内容", raw_text=text.strip())

    ids = {str(i).upper() for i in option_ids if i}
    head, _, tail = raw.partition(" ")
    head_up = head.upper()

    # 3. 选项匹配
    if len(head_up) == 1 and head_up.isalpha():
        if not ids or head_up in ids:
            return ParsedReply(
                decision_id, ReplyKind.OPTION, choice=head_up,
                comment=tail.strip() or None, raw_text=text.strip(),
            )
        # 单字母不是方案，但带了意见文字 → 自定义意见（约定 "C + 自定义意见"）
        if tail.strip():
            return ParsedReply(
                decision_id, ReplyKind.CUSTOM, choice=head_up,
                comment=tail.strip(), raw_text=text.strip(),
            )
        # 孤立单字母且不是任何方案 → 无效选项（疑似敲错/未完成）
        return ParsedReply(decision_id, ReplyKind.OPTION, choice=head_up, valid=False,
                           invalid_reason=f"无效选项：{head_up}（可选：{sorted(ids)}）",
                           raw_text=text.strip())

    if head_up in ids:
        return ParsedReply(
            decision_id, ReplyKind.OPTION, choice=head_up,
            comment=tail.strip() or None, raw_text=text.strip(),
        )

    # 4. 其他文本：
    #    有方案选项时，裸文本视为无效（防"收到/你好"等客套话被误当决策），
    #    要求按约定回复；无方案选项时，整条文本即决策意见。
    if ids:
        return ParsedReply(
            decision_id, ReplyKind.CUSTOM, valid=False,
            invalid_reason="请按约定回复：选项字母（如 A）、C + 自定义意见、STOP 或 <决策编号> <回复>",
            raw_text=text.strip(),
        )
    return ParsedReply(
        decision_id, ReplyKind.CUSTOM, choice="C", comment=raw,
        raw_text=text.strip(),
    )


def split_reply_stream(chunk: str) -> list[str]:
    """把会话文件里的一段文本拆成多条候选回复（按行）。"""
    return [ln.strip() for ln in (chunk or "").splitlines() if ln.strip()]
