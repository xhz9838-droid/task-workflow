# -*- coding: utf-8 -*-
"""统一启动预检：user_id 可选、PASS/WARN/BLOCKED 分类、非阻塞失败不终止。"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, _SCRIPTS)

import _config  # noqa: E402
import preflight  # noqa: E402
import project_resolver  # noqa: E402


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_home(tmp_path):
    root = tmp_path / "wf"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "_config.py").write_text("# marker\n", encoding="utf-8")
    (root / "config" / "projects").mkdir(parents=True)
    (root / "config" / "users").mkdir(parents=True)
    (root / "config" / "workflow.yaml").write_text(
        "execution_root: \"${WORKFLOW_HOME}/execution\"\n", encoding="utf-8")
    repo = tmp_path / "repo-be"
    repo.mkdir()
    (root / "config" / "projects" / "demo.yaml").write_text(
        "project:\n"
        "  key: demo\n"
        "  name: Demo\n"
        "  repositories:\n"
        "    - key: be\n"
        "      role: backend\n"
        "      technology: java-maven\n"
        "      path: \"%s\"\n"
        "      require_git: false\n"
        "  agents:\n"
        "    dw-java-backend: true\n" % repo.as_posix(),
        encoding="utf-8")
    return root


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = make_home(tmp_path)
    monkeypatch.setenv("WORKFLOW_HOME", str(root))
    monkeypatch.setattr(_config, "_root_cache", None)
    # 默认：无 user（不读真实机器配置）
    monkeypatch.setattr(preflight, "resolve_user_id_optional",
                        lambda explicit=None: ("", "unresolved: test"))
    monkeypatch.setattr(project_resolver, "resolve_user_id_optional",
                        lambda explicit=None: ("", "unresolved: test"))
    return root


def _checks(r, name):
    return [c for c in r["checks"] if c["name"] == name]


def test_preflight_ok_without_user(home):
    r = preflight.run("demo", ["101"])
    assert r["ok"] is True, [c for c in r["checks"] if c["status"] == "BLOCKED"]
    assert r["task_ids"] == ["101"]
    user = _checks(r, "user")[0]
    assert user["status"] == "WARN"            # 缺 user 不阻塞
    assert _checks(r, "project_config")[0]["status"] == "PASS"


def test_preflight_multi_tasks_pass_through(home):
    r = preflight.run("demo", ["3442", "3443", "3444", "3445"])
    assert r["task_ids"] == ["3442", "3443", "3444", "3445"]
    assert r["ok"] is True


def test_preflight_dedupes_tasks(home):
    r = preflight.run("demo", ["101", "101", "102"])
    assert r["task_ids"] == ["101", "102"]
    assert any("去重" in a for a in r["actions"])


def test_preflight_invalid_args_blocked(home):
    r = preflight.run("demo", ["other", "101"])   # 两个 project_key
    assert r["ok"] is False
    assert _checks(r, "invocation")[0]["status"] == "BLOCKED"


def test_repo_missing_without_user_is_warn(tmp_path, monkeypatch):
    root = make_home(tmp_path)
    # 去掉仓库 path：无 user 映射时应降级 WARN
    (root / "config" / "projects" / "demo.yaml").write_text(
        "project:\n  key: demo\n  repositories:\n"
        "    - key: be\n      role: backend\n", encoding="utf-8")
    monkeypatch.setenv("WORKFLOW_HOME", str(root))
    monkeypatch.setattr(_config, "_root_cache", None)
    monkeypatch.setattr(preflight, "resolve_user_id_optional",
                        lambda explicit=None: ("", "unresolved: test"))
    monkeypatch.setattr(project_resolver, "resolve_user_id_optional",
                        lambda explicit=None: ("", "unresolved: test"))
    r = preflight.run("demo", ["101"])
    assert r["ok"] is True
    assert _checks(r, "repo:be")[0]["status"] == "WARN"


def test_repo_path_missing_with_user_blocked(tmp_path, monkeypatch):
    root = make_home(tmp_path)
    (root / "config" / "users" / "u.yaml").write_text(
        "user:\n  id: u\n", encoding="utf-8")
    monkeypatch.setenv("WORKFLOW_HOME", str(root))
    monkeypatch.setattr(_config, "_root_cache", None)
    monkeypatch.setattr(preflight, "resolve_user_id_optional",
                        lambda explicit=None: ("u", "explicit"))
    monkeypatch.setattr(project_resolver, "resolve_user_id_optional",
                        lambda explicit=None: ("u", "explicit"))
    # 用户路径指向不存在的目录 → 明确 BLOCKED
    (root / "config" / "users" / "u.yaml").write_text(
        "user:\n  id: u\n  project_paths:\n    demo:\n      be: \"%s\"\n"
        % (tmp_path / "nope").as_posix(), encoding="utf-8")
    r = preflight.run("demo", ["101"], user="u")
    assert r["ok"] is False
    assert _checks(r, "repo:be")[0]["status"] == "BLOCKED"


def _boom(_tid):
    raise RuntimeError("禅道不可达")


def test_task_detail_failure_is_warn(home):
    r = preflight.run("demo", ["101"], fetch_tasks=True, fetcher=_boom)
    assert r["ok"] is True
    assert _checks(r, "task_detail:101")[0]["status"] == "WARN"


def test_task_detail_failure_required_blocks(home):
    r = preflight.run("demo", ["101"], fetch_tasks=True, require_tasks=True, fetcher=_boom)
    assert r["ok"] is False
    assert _checks(r, "task_detail:101")[0]["status"] == "BLOCKED"


def test_build_context_without_user(home):
    """user_id 解析不到时 context 仍可构建，user_id 为空。"""
    r = preflight.run("demo", ["101"])
    ctx = r["context"]
    assert ctx["user_id"] == ""
    assert ctx["project_key"] == "demo"


def test_preflight_main_exit_codes(home, capsys):
    assert preflight.main(["demo", "101", "--json"]) == 0
    capsys.readouterr()
    assert preflight.main(["demo", "other", "101", "--json"]) == 2


def test_user_config_missing_degrades_to_warn(tmp_path, monkeypatch):
    """自动解析出的用户配置不存在：降级为无用户上下文，WARN 不阻塞。"""
    root = make_home(tmp_path)
    monkeypatch.setenv("WORKFLOW_HOME", str(root))
    monkeypatch.setattr(_config, "_root_cache", None)
    monkeypatch.setattr(preflight, "resolve_user_id_optional",
                        lambda explicit=None: ("ghost", "env:WORKFLOW_USER_ID"))
    monkeypatch.setattr(project_resolver, "resolve_user_id_optional",
                        lambda explicit=None: ("ghost", "env:WORKFLOW_USER_ID"))
    r = preflight.run("demo", ["101"])
    assert r["ok"] is True
    assert _checks(r, "user")[0]["status"] == "WARN"
    assert r["context"]["user_id"] == ""
    assert any("无用户上下文" in a for a in r["actions"])


def test_multiple_blocked_checks(tmp_path, monkeypatch):
    """多个检查同时失败：仍全部报告，不短路。"""
    root = make_home(tmp_path)
    (root / "config" / "users" / "u.yaml").write_text(
        "user:\n  id: u\n  project_paths:\n    demo:\n      be: \"%s\"\n"
        % (tmp_path / "missing").as_posix(), encoding="utf-8")
    monkeypatch.setenv("WORKFLOW_HOME", str(root))
    monkeypatch.setattr(_config, "_root_cache", None)
    monkeypatch.setattr(preflight, "resolve_user_id_optional",
                        lambda explicit=None: ("u", "explicit"))
    monkeypatch.setattr(project_resolver, "resolve_user_id_optional",
                        lambda explicit=None: ("u", "explicit"))
    r = preflight.run("demo", ["101"], user="u", fetch_tasks=True,
                      require_tasks=True, fetcher=_boom)
    blocked = [c["name"] for c in r["checks"] if c["status"] == "BLOCKED"]
    assert r["ok"] is False
    assert "repo:be" in blocked and "task_detail:101" in blocked


def test_repo_check_cli_has_output_and_exit_code(home, tmp_path):
    """repo_check.py 不再是静默模块：有输出、退出码明确。"""
    env = dict(os.environ, WORKFLOW_HOME=str(home), PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, "-I", os.path.join(_SCRIPTS, "repo_check.py"),
           "--project", "demo", "--json"]
    ok = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)
    assert ok.returncode == 0
    assert "be" in (ok.stdout or "")

    # 仓库路径改为不存在 → 退出码 1，并给出问题明细
    (home / "config" / "projects" / "demo.yaml").write_text(
        "project:\n  key: demo\n  repositories:\n"
        "    - key: be\n      role: backend\n      path: \"%s\"\n"
        % (tmp_path / "missing").as_posix(), encoding="utf-8")
    bad = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)
    assert bad.returncode == 1
    assert "路径不存在" in (bad.stdout or "")
