# -*- coding: utf-8 -*-
"""调用参数解析与任务→项目归属匹配测试（scripts/_args.py）。

覆盖：#3415 不是完整参数（project_key 缺失不推断）、project_key/task_id 独立解析、
歧义报错、禅道任务→项目归属唯一命中 / 不唯一 / 无命中。
"""
import json

import pytest

from _args import ArgsError, main, match_project, parse_invocation


# ---------------------------------------------------------- parse_invocation
def test_task_only_with_hash():
    """`#3415` 只是任务号：project_key 缺失，不得推断项目。"""
    r = parse_invocation(["#3415"])
    assert r == {"project_key": None, "task_id": "3415", "missing": ["project_key"]}


def test_task_only_without_hash():
    r = parse_invocation(["3415"])
    assert r == {"project_key": None, "task_id": "3415", "missing": ["project_key"]}


def test_project_and_task_both_orders():
    for tokens in (["jeebootx", "3415"], ["jeebootx", "#3415"], ["3415", "jeebootx"]):
        r = parse_invocation(tokens)
        assert r == {"project_key": "jeebootx", "task_id": "3415", "missing": []}


def test_project_key_with_hash_prefix_stripped():
    r = parse_invocation(["#jeebootx", "3415"])
    assert r["project_key"] == "jeebootx"


def test_missing_task_id():
    r = parse_invocation(["jeebootx"])
    assert r == {"project_key": "jeebootx", "task_id": None, "missing": ["task_id"]}


def test_empty_invocation():
    r = parse_invocation([])
    assert r["missing"] == ["project_key", "task_id"]


def test_two_task_ids_rejected():
    with pytest.raises(ArgsError):
        parse_invocation(["3415", "3416"])


def test_two_project_keys_rejected():
    with pytest.raises(ArgsError):
        parse_invocation(["jeebootx", "demo-react"])


def test_option_like_token_rejected():
    with pytest.raises(ArgsError):
        parse_invocation(["--user", "xuhongzu", "3415"])


def test_illegal_project_key_rejected():
    with pytest.raises(ArgsError):
        parse_invocation(["bad key", "3415"])


# ---------------------------------------------------------- match_project
PROJECTS = [
    {"key": "jeebootx", "name": "jeebootx", "zentao_project": "3"},
    {"key": "demo-react", "name": "demo", "zentao_project": ["7", "demo-react-zt"]},
    {"key": "no-map", "name": "nomap"},
]


def test_match_by_zentao_project_id():
    assert match_project({"id": "3415", "project": "3"}, PROJECTS) == "jeebootx"


def test_match_by_project_name():
    assert match_project({"id": "1", "projectName": "demo"}, PROJECTS) == "demo-react"


def test_match_by_zentao_project_list():
    assert match_project({"id": "1", "project": "demo-react-zt"}, PROJECTS) == "demo-react"


def test_no_match_returns_none():
    """无命中：返回 None → 询问用户，不推断。"""
    assert match_project({"id": "1", "project": "999"}, PROJECTS) is None


def test_ambiguous_returns_none():
    """多命中：返回 None → 询问用户。"""
    projects = [{"key": "a", "name": "same"}, {"key": "b", "name": "same"}]
    assert match_project({"id": "1", "projectName": "same"}, projects) is None


def test_empty_inputs_return_none():
    assert match_project({}, PROJECTS) is None
    assert match_project({"id": "1"}, []) is None
    assert match_project({"id": "1", "project": ""}, PROJECTS) is None


# ---------------------------------------------------------- CLI
def test_cli_parse_prints_json(capsys):
    assert main(["pytest", "parse", "#3415"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["task_id"] == "3415"
    assert out["missing"] == ["project_key"]


def test_cli_parse_ambiguous_exit_code(capsys):
    assert main(["pytest", "parse", "3415", "3416"]) == 3
    assert "任务号" in capsys.readouterr().err


def test_cli_match_project_unique(tmp_path, monkeypatch, capsys):
    """CLI 归属验证：唯一命中打印 project_key。"""
    home = tmp_path / "home"
    (home / "config" / "projects").mkdir(parents=True)
    (home / "config" / "projects" / "jeebootx.yaml").write_text(
        "project:\n  key: jeebootx\n  name: jeebootx\n  zentao_project: \"3\"\n", encoding="utf-8"
    )
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps({"id": "3415", "project": "3"}), encoding="utf-8")
    monkeypatch.setenv("WORKFLOW_HOME", str(home))
    assert main(["pytest", "match-project", "--task-json", str(task_file), "--home", str(home)]) == 0
    assert capsys.readouterr().out.strip() == "jeebootx"


def test_cli_match_project_ambiguous_exit_code(tmp_path, monkeypatch, capsys):
    """CLI 归属验证：无法唯一确定 → 退出码 4（须询问用户）。"""
    home = tmp_path / "home"
    (home / "config" / "projects").mkdir(parents=True)
    for key in ("a", "b"):
        (home / "config" / "projects" / ("%s.yaml" % key)).write_text(
            "project:\n  key: %s\n  name: same\n" % key, encoding="utf-8"
        )
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps({"id": "1", "project": "same"}), encoding="utf-8")
    monkeypatch.setenv("WORKFLOW_HOME", str(home))
    assert main(["pytest", "match-project", "--task-json", str(task_file), "--home", str(home)]) == 4
    assert "询问用户" in capsys.readouterr().err
