# -*- coding: utf-8 -*-
"""单元测试：数据模型 / 检测器 / 回复解析。"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from human_decision.models import (
    DecisionLevel, DecisionStatus, ReplyKind, TRANSITIONS, new_decision_id,
)
from human_decision.decision_detector import detect
from human_decision.reply_parser import parse_reply


# --------------------------------------------------------------- models
def test_decision_id_unique():
    ids = {new_decision_id("3413") for _ in range(50)}
    assert len(ids) == 50
    assert all(i.startswith("DEC-3413-") for i in ids)


def test_status_transitions_guard():
    # WAITING_REPLY 可到 DECISION_RECEIVED，不可到 COMPLETED
    assert DecisionStatus.DECISION_RECEIVED in TRANSITIONS[DecisionStatus.WAITING_REPLY]
    assert DecisionStatus.COMPLETED not in TRANSITIONS[DecisionStatus.WAITING_REPLY]
    # COMPLETED 是终态
    assert TRANSITIONS[DecisionStatus.COMPLETED] == set()
    # 超时后仍可迟到回复
    assert DecisionStatus.DECISION_RECEIVED in TRANSITIONS[DecisionStatus.DECISION_TIMEOUT]


# --------------------------------------------------------------- detector
def test_detect_p0_delete_data():
    r = detect(question="需要删除生产用户表数据", background="数据清理")
    assert r.level == DecisionLevel.P0


def test_detect_p0_ddl():
    r = detect(question="修改数据库结构，加一个字段", background="alter table users add column")
    assert r.level == DecisionLevel.P0


def test_detect_p1_multi_option():
    r = detect(question="两种方案需要确认", background="方案A改逻辑，方案B改架构")
    assert r.level == DecisionLevel.P1


def test_detect_p2_normal():
    r = detect(question="修复一个按钮样式", background="css 颜色调整")
    assert r.level == DecisionLevel.P2


def test_detect_explicit_level_wins():
    r = detect(question="修复样式", explicit_level="P0")
    assert r.level == DecisionLevel.P0
    assert "显式" in r.reason


# --------------------------------------------------------------- reply parser
def test_parse_option_letter():
    p = parse_reply("A", ["A", "B"])
    assert p.valid and p.kind == ReplyKind.OPTION and p.choice == "A"


def test_parse_option_with_comment():
    p = parse_reply("B 用第二种，注意兼容", ["A", "B"])
    assert p.valid and p.choice == "B" and p.comment == "用第二种，注意兼容"


def test_parse_stop():
    for t in ("STOP", "stop", "停止", "暂停"):
        p = parse_reply(t, ["A", "B"])
        assert p.valid and p.kind == ReplyKind.STOP, t


def test_parse_custom_opinion():
    # 无方案选项：裸文本 = 自定义意见
    p = parse_reply("按你们原来的做法处理", [])
    assert p.valid and p.kind == ReplyKind.CUSTOM and p.comment == "按你们原来的做法处理"


def test_parse_custom_via_c_with_options():
    # 有方案选项：约定 "C + 自定义意见"
    p = parse_reply("C 按你们原来的做法处理", ["A", "B"])
    assert p.valid and p.kind == ReplyKind.CUSTOM and p.choice == "C"
    assert p.comment == "按你们原来的做法处理"


def test_parse_bare_text_invalid_when_options():
    # 有方案选项时裸文本（如"收到"）不得被当作决策
    p = parse_reply("收到", ["A", "B"])
    assert not p.valid and "请按约定回复" in p.invalid_reason


def test_parse_invalid_letter():
    p = parse_reply("X", ["A", "B"])
    assert not p.valid and "无效选项" in p.invalid_reason


def test_parse_with_decision_id():
    p = parse_reply("DEC-3413-001 A", ["A", "B"])
    assert p.decision_id == "DEC-3413-001" and p.choice == "A" and p.valid


def test_parse_decision_id_chinese_colon():
    p = parse_reply("DEC-3413-001：B 附注", ["A", "B"])
    assert p.decision_id == "DEC-3413-001" and p.choice == "B" and p.comment == "附注"


def test_parse_empty():
    p = parse_reply("   ", ["A"])
    assert not p.valid
