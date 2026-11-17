# -*- coding: utf-8 -*-
"""仓库识别与路径校验测试（任务 §九·仓库路径测试）。仅 tmp 目录，只读 Git 命令。"""
from __future__ import annotations

import os
import subprocess

import pytest

from repo_check import check_project_repos, check_repo, detect_technology, _remote_equal


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], capture_output=True, check=False)


def _make_git_repo(path, remote="git@example.com:team/app.git", dirty=False):
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], capture_output=True, check=True)
    if remote:
        _git(path, "remote", "add", "origin", remote)
    with open(os.path.join(str(path), "a.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    _git(path, "add", "-A")
    _git(path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    if dirty:
        with open(os.path.join(str(path), "dirty.txt"), "w", encoding="utf-8") as f:
            f.write("y")
    return str(path)


# --------------------------------------------------------------- 正常/异常
def test_ok_git_repo(tmp_path):
    p = _make_git_repo(tmp_path / "app")
    r = check_repo("app", p, expect_role="backend", role="backend", expect_remote="git@example.com:team/app.git")
    assert r.ok, r.problems
    assert r.details.get("git") is True
    assert r.details.get("dirty") is False


def test_path_missing_blocked(tmp_path):
    r = check_repo("app", str(tmp_path / "nope"))
    assert r.status == "blocked"
    assert "路径不存在" in r.problems[0]


def test_path_not_dir_blocked(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    r = check_repo("app", str(f))
    assert r.status == "blocked"
    assert "不是目录" in r.problems[0]


def test_not_git_blocked(tmp_path):
    d = tmp_path / "plain"
    os.makedirs(d)
    r = check_repo("app", str(d))
    assert r.status == "blocked"
    assert "不是 Git 仓库" in r.problems[0]


def test_git_root_mismatch(tmp_path):
    repo = _make_git_repo(tmp_path / "app")
    sub = os.path.join(repo, "src", "main")
    os.makedirs(sub, exist_ok=True)
    r = check_repo("app", sub)
    assert r.status == "mismatch"
    assert any("Git 根目录" in p for p in r.problems)


def test_remote_mismatch(tmp_path):
    p = _make_git_repo(tmp_path / "app", remote="git@example.com:team/app.git")
    r = check_repo("app", p, expect_remote="git@example.com:team/other.git")
    assert r.status == "mismatch"
    assert any("remote" in p for p in r.problems)


def test_remote_equal_normalizes_suffix():
    assert _remote_equal("https://x/y/app.git", "https://x/y/app")
    assert not _remote_equal("https://x/y/app.git", "https://x/y/other.git")


def test_multi_repo_project(tmp_path):
    a = _make_git_repo(tmp_path / "backend")
    b = _make_git_repo(tmp_path / "frontend", remote="git@example.com:team/ui.git")
    cfg = {"key": "p1", "repositories": [
        {"key": "backend", "path": a, "role": "backend"},
        {"key": "frontend", "path": b, "role": "frontend", "remote_url": "git@example.com:team/ui.git"},
    ]}
    res = check_project_repos(cfg, {})
    assert [r.repo_key for r in res] == ["backend", "frontend"]
    assert all(r.ok for r in res), [(r.repo_key, r.problems) for r in res]


def test_dirty_worktree_recorded_not_blocking(tmp_path):
    p = _make_git_repo(tmp_path / "app", dirty=True)
    r = check_repo("app", p)
    assert r.ok
    assert r.details.get("dirty") is True


def test_role_mismatch(tmp_path):
    p = _make_git_repo(tmp_path / "app")
    r = check_repo("app", p, role="frontend", expect_role="backend")
    assert r.status == "mismatch"


def test_disabled_repo_skipped(tmp_path):
    p = _make_git_repo(tmp_path / "app")
    cfg = {"key": "p1", "repositories": [
        {"key": "app", "path": p},
        {"key": "off", "path": "/nope", "enabled": False},
    ]}
    res = check_project_repos(cfg, {})
    assert [r.repo_key for r in res] == ["app"]


# --------------------------------------------------------------- 路径形态
def test_windows_path_variants(tmp_path):
    p = _make_git_repo(tmp_path / "app")
    alt = p.replace("\\", "/") if "\\" in p else p.replace("/", "\\")
    r = check_repo("app", alt)
    assert r.ok, (alt, r.problems)


def test_repo_paths_fallback_to_config_path():
    from project_resolver import repo_paths_for

    cfg = {"project": {"key": "p1", "repositories": [{"key": "backend", "path": "/from-env-path"}]}}
    paths = repo_paths_for(cfg, None)
    assert paths["backend"] == "/from-env-path"


# --------------------------------------------------------------- 技术栈识别
@pytest.mark.parametrize("files,expected", [
    ({"pom.xml": ""}, "java-maven"),
    ({"build.gradle": ""}, "java-gradle"),
    ({"requirements.txt": ""}, "python"),
    ({"pyproject.toml": ""}, "python"),
    ({}, "unknown"),
])
def test_detect_technology_markers(tmp_path, files, expected):
    d = tmp_path / "proj"
    os.makedirs(d)
    for name, content in files.items():
        (d / name).write_text(content, encoding="utf-8")
    assert detect_technology(str(d)) == expected


def test_detect_vue_vs_react_vs_uniapp(tmp_path):
    import json

    vue = tmp_path / "vue"
    os.makedirs(vue)
    (vue / "package.json").write_text(json.dumps({"dependencies": {"vue": "^3"}}), encoding="utf-8")
    assert detect_technology(str(vue)) == "vue"

    rj = tmp_path / "react"
    os.makedirs(rj)
    (rj / "package.json").write_text(json.dumps({"dependencies": {"react": "^18"}}), encoding="utf-8")
    assert detect_technology(str(rj)) == "react"

    uni = tmp_path / "uni"
    os.makedirs(uni)
    (uni / "manifest.json").write_text("{}", encoding="utf-8")
    (uni / "package.json").write_text(json.dumps({"dependencies": {"@dcloudio/uni-app": "*"}}), encoding="utf-8")
    assert detect_technology(str(uni)) == "uni-app"
