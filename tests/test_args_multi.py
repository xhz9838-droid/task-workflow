# -*- coding: utf-8 -*-
"""调用参数解析：多任务号、--tasks、去重、非法输入与历史单任务兼容。"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from _args import ArgsError, parse_invocation  # noqa: E402


def test_single_task_legacy():
    r = parse_invocation(["jeebootx", "3442"])
    assert r["project_key"] == "jeebootx"
    assert r["task_ids"] == ["3442"]
    assert r["task_id"] == "3442"          # 单任务兼容字段
    assert r["missing"] == []


def test_single_task_hash_prefix():
    r = parse_invocation(["jeebootx", "#3415"])
    assert r["task_ids"] == ["3415"]
    assert r["task_id"] == "3415"


def test_two_tasks():
    r = parse_invocation(["jeebootx", "3442", "3443"])
    assert r["task_ids"] == ["3442", "3443"]
    assert r["task_id"] is None             # 多任务不合并为单个 task_id


def test_four_tasks_not_merged():
    r = parse_invocation(["jeebootx", "3442", "3443", "3444", "3445"])
    assert r["task_ids"] == ["3442", "3443", "3444", "3445"]
    assert len(r["task_ids"]) == 4


def test_tasks_option_comma():
    r = parse_invocation(["jeebootx", "--tasks", "3442,3443,3444,3445"])
    assert r["task_ids"] == ["3442", "3443", "3444", "3445"]


def test_tasks_option_equals_and_hash():
    r = parse_invocation(["jeebootx", "--tasks=#3442, #3443"])
    assert r["task_ids"] == ["3442", "3443"]


def test_tasks_option_space_separated_value():
    r = parse_invocation(["jeebootx", "--tasks", "3442 3443"])
    assert r["task_ids"] == ["3442", "3443"]


def test_duplicate_task_ids_deduped_in_order():
    r = parse_invocation(["jeebootx", "3442", "3443", "3442", "--tasks", "3443"])
    assert r["task_ids"] == ["3442", "3443"]
    assert r["duplicate_task_ids"] == ["3442", "3443"]


def test_invalid_task_in_tasks_option():
    with pytest.raises(ArgsError, match="非法任务号"):
        parse_invocation(["jeebootx", "--tasks", "3442,abc"])


def test_tasks_option_missing_value():
    with pytest.raises(ArgsError, match="缺少任务号"):
        parse_invocation(["jeebootx", "--tasks"])


def test_missing_project_key():
    r = parse_invocation(["#3415"])
    assert r["project_key"] is None
    assert r["task_ids"] == ["3415"]
    assert "project_key" in r["missing"]


def test_second_project_key_rejected():
    with pytest.raises(ArgsError, match="多个 project_key"):
        parse_invocation(["jeebootx", "other", "3442"])


def test_unknown_option_rejected_with_usage():
    with pytest.raises(ArgsError, match="不支持的选项") as ei:
        parse_invocation(["jeebootx", "--parallel", "3442"])
    assert "--tasks" in str(ei.value) or "用法" in str(ei.value)


def test_cli_parse_returns_task_ids(capsys):
    from _args import main
    rc = main(["_args.py", "parse", "jeebootx", "3442", "3443"])
    assert rc == 0
    r = json.loads(capsys.readouterr().out)
    assert r["task_ids"] == ["3442", "3443"]
