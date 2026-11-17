# -*- coding: utf-8 -*-
"""DEC-ID 解析回归：多段连字符任务号的显式决策绑定（D8）。

DEC-HITL-A02-5A-12345678 旧正则被截断为 DEC-HITL-A02 → 绑定失效。
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PARENT = os.path.dirname(_PKG)
for _p in (_PARENT, _PKG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human_decision.reply_parser import parse_reply  # noqa: E402
from human_decision.decision_detector import DEC_ID_RE  # noqa: E402


def test_multi_dash_decision_id_not_truncated():
    p = parse_reply("DEC-HITL-A02-3-13484101 A", ["A", "B"])
    assert p.decision_id == "DEC-HITL-A02-3-13484101"
    assert p.choice == "A"
    assert p.valid


def test_multi_dash_with_alpha_suffix():
    p = parse_reply("DEC-HITL-A02-5A-12400001 B", ["A", "B"])
    assert p.decision_id == "DEC-HITL-A02-5A-12400001"
    assert p.choice == "B"


def test_simple_decision_id_still_works():
    p = parse_reply("DEC-3413-001 A", ["A", "B"])
    assert p.decision_id == "DEC-3413-001"
    assert p.choice == "A"


def test_full_width_separator_and_comment():
    p = parse_reply("DEC-HITL-E2E-3-09292801：A 很好", ["A", "B"])
    assert p.decision_id == "DEC-HITL-E2E-3-09292801"
    assert p.choice == "A"
    assert p.comment == "很好"


def test_dec_id_regex_requires_word_boundary():
    # 非 DEC- 起头的文本不误捕（无词边界）
    assert DEC_ID_RE.search("XDEC-3413-1 不是编号") is None
    # DEC- 形状的无效编号整体捕获（回执走「未找到决策」）
    m = DEC_ID_RE.search("DEC-3413-ignored B")
    assert m and m.group(1) == "DEC-3413-ignored"
