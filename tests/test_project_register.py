# -*- coding: utf-8 -*-
"""项目注册测试（任务 §九·项目注册测试）。仅 tmp 假目录 + 临时 Git 仓库。"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

import project_register as reg
import project_resolver as pr
from project_register import RegisterError, apply_plan, build_plan
from _config import _read_yaml


def _git_repo(path, remote="git@example.com:team/x.git"):
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], capture_output=True, check=True)
    return str(path)


def _write_project(home, key, block):
    pdir = os.path.join(str(home), "config", "projects")
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, key + ".yaml"), "w", encoding="utf-8") as f:
        json.dump({"project": block}, f, ensure_ascii=False)


@pytest.fixture
def home(fake_home):
    return fake_home


@pytest.fixture
def repo1(tmp_path):
    return _git_repo(tmp_path / "backend")


def _plan(home, repo1, **kw):
    args = dict(project_key="smart-sanitation", name="智慧环卫管理平台",
                zentao_project_id="125", user_id="alice",
                repos={"backend": {"path": repo1, "role": "backend",
                                   "remote_url": "git@example.com:team/x.git"}},
                home=home)
    args.update(kw)
    return build_plan(**args)


# --------------------------------------------------------------- 正常注册
def test_register_new_project_ok(home, repo1):
    plan = _plan(home, repo1)
    assert plan["fingerprint"]
    assert plan["project_block"]["repositories"][0]["technology"]  # 技术栈已识别
    result = apply_plan(plan, confirm=plan["fingerprint"])
    assert not result["dry_run"]
    proj = os.path.join(str(home), "config", "projects", "smart-sanitation.yaml")
    assert os.path.exists(proj)
    data = _read_yaml(proj)
    assert data["project"]["zentao"]["project_id"] == 125
    # 个人路径进用户文件，不进公共配置
    assert "path" not in data["project"]["repositories"][0]
    user = _read_yaml(os.path.join(str(home), "config", "users", "alice.yaml"))
    assert user["user"]["project_paths"]["smart-sanitation"]["backend"] == repo1


# --------------------------------------------------------------- 查重
def test_duplicate_project_key_rejected(home, repo1):
    _write_project(home, "smart-sanitation", {"key": "smart-sanitation"})
    with pytest.raises(RegisterError, match="project_key 已存在"):
        _plan(home, repo1)


def test_duplicate_zentao_project_rejected(home, repo1):
    _write_project(home, "other", {"key": "other", "zentao": {"project_id": 125}})
    with pytest.raises(RegisterError, match="已注册"):
        _plan(home, repo1)


def test_same_zentao_via_legacy_field_rejected(home, repo1):
    _write_project(home, "legacy", {"key": "legacy", "zentao_project": ["125", "旧名"]})
    with pytest.raises(RegisterError, match="已注册"):
        _plan(home, repo1)


# --------------------------------------------------------------- 确认与 dry-run
def test_dry_run_writes_nothing(home, repo1):
    plan = _plan(home, repo1)
    r = apply_plan(plan, confirm=plan["fingerprint"], dry_run=True)
    assert r["dry_run"] is True
    assert not os.path.exists(os.path.join(str(home), "config", "projects", "smart-sanitation.yaml"))


def test_wrong_confirm_rejected(home, repo1):
    plan = _plan(home, repo1)
    with pytest.raises(RegisterError, match="指纹不匹配"):
        apply_plan(plan, confirm="bad-confirm")
    assert not os.path.exists(os.path.join(str(home), "config", "projects", "smart-sanitation.yaml"))


# --------------------------------------------------------------- 用户配置安全
def test_no_overwrite_existing_user_mapping(home, repo1, tmp_path):
    upath = os.path.join(str(home), "config", "users", "alice.yaml")
    os.makedirs(os.path.dirname(upath), exist_ok=True)
    with open(upath, "w", encoding="utf-8") as f:
        json.dump({"user": {"id": "alice", "project_paths": {
            "smart-sanitation": {"backend": "D:/alice/old-backend"}}}}, f)
    plan = _plan(home, repo1)
    with pytest.raises(RegisterError, match="拒绝覆盖"):
        apply_plan(plan, confirm=plan["fingerprint"])
    assert _read_yaml(upath)["user"]["project_paths"][
        "smart-sanitation"]["backend"] == "D:/alice/old-backend"


def test_existing_user_keys_preserved(home, repo1):
    upath = os.path.join(str(home), "config", "users", "alice.yaml")
    os.makedirs(os.path.dirname(upath), exist_ok=True)
    with open(upath, "w", encoding="utf-8") as f:
        json.dump({"user": {"id": "alice", "display_name": "爱丽丝",
                            "task_source": {"provider": "zentao", "account": "alice"}}}, f)
    plan = _plan(home, repo1)
    apply_plan(plan, confirm=plan["fingerprint"])
    u = _read_yaml(upath)["user"]
    assert u["display_name"] == "爱丽丝" and u["task_source"]["account"] == "alice"
    assert u["project_paths"]["smart-sanitation"]["backend"] == repo1


# --------------------------------------------------------------- 缺失/坏输入
def test_missing_repo_path_blocked(home):
    with pytest.raises(RegisterError, match="BLOCKED"):
        build_plan(project_key="p1", name="P1", repos={"r": {"path": "/nope/xx"}}, home=home)


def test_no_repo_rejected(home):
    with pytest.raises(RegisterError, match="至少需要一个仓库"):
        build_plan(project_key="p1", name="P1", repos={}, home=home)


def test_bad_project_key_rejected(home, repo1):
    with pytest.raises(RegisterError, match="非法 project_key"):
        _plan(home, repo1, project_key="bad key/with:chars")


def test_malformed_user_config_surfaces(home, repo1):
    upath = os.path.join(str(home), "config", "users", "alice.yaml")
    os.makedirs(os.path.dirname(upath), exist_ok=True)
    with open(upath, "w", encoding="utf-8") as f:
        f.write("user: [unclosed")
    plan = _plan(home, repo1)
    with pytest.raises(Exception):
        apply_plan(plan, confirm=plan["fingerprint"])


# --------------------------------------------------------------- 注册后可解析
def test_registered_project_resolvable(home, repo1):
    plan = _plan(home, repo1)
    apply_plan(plan, confirm=plan["fingerprint"])
    r = pr.resolve_by_task({"project": "125"}, registry=pr.load_registry(home))
    assert r["status"] == "resolved" and r["project_key"] == "smart-sanitation"
