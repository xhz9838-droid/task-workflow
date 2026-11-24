# -*- coding: utf-8 -*-
"""HITL 回复格式解析：A/B/C、DEC-ID、标点、自然语言、防误判。"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)          # human_decision/
_PARENT = os.path.dirname(_PKG)        # agent-manager/
sys.path[:0] = [_PARENT, _PKG]

from human_decision.reply_parser import parse_reply  # noqa: E402


IDS = ["A", "B", "C"]


def test_bare_option():
    r = parse_reply("B", IDS)
    assert (r.decision_id, r.choice, r.valid) == (None, "B", True)


def test_option_with_space_comment():
    r = parse_reply("A 先做备份", IDS)
    assert (r.choice, r.comment, r.valid) == ("A", "先做备份", True)


def test_option_with_chinese_comma_comment():
    r = parse_reply("C，建议先修改配置再执行", IDS)
    assert (r.choice, r.comment, r.valid) == ("C", "建议先修改配置再执行", True)


def test_option_with_colon_comment():
    r = parse_reply("B: 同意", IDS)
    assert (r.choice, r.comment) == ("B", "同意")


def test_dec_id_option_comment():
    r = parse_reply("DEC-HITL-E2E-20261123-14403301 C 自定义意见", IDS)
    assert r.decision_id == "DEC-HITL-E2E-20261123-14403301"
    assert (r.choice, r.comment, r.valid) == ("C", "自定义意见", True)


def test_dec_id_option_chinese_comma_comment():
    r = parse_reply("DEC-3442-16301801 C，先改配置", IDS)
    assert r.decision_id == "DEC-3442-16301801"
    assert (r.choice, r.comment) == ("C", "先改配置")


def test_natural_language_choice():
    r = parse_reply("我选择 A，按第一个方案执行。", IDS)
    assert (r.choice, r.valid) == ("A", True)
    assert "按第一个方案执行" in (r.comment or "")


def test_natural_language_choose_c():
    r = parse_reply("选择 C，但是先不要部署。", IDS)
    assert (r.choice, r.valid) == ("C", True)
    assert "先不要部署" in (r.comment or "")


def test_arbitrary_letter_not_treated_as_choice():
    r = parse_reply("我觉得 A 不行", IDS)
    assert r.valid is False  # 不在明确“选择”语境，要求澄清


def test_invalid_option_letter():
    r = parse_reply("Z", IDS)
    assert r.valid is False and r.choice == "Z"


def test_stop():
    r = parse_reply("STOP", IDS)
    assert r.kind.value == "stop"


def test_dec_id_without_choice():
    r = parse_reply("DEC-3442-16301801", IDS)
    assert r.valid is False
