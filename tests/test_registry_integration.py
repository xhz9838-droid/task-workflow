# -*- coding: utf-8 -*-
"""注册/解析集成测试（任务 §九·工作流集成测试，不依赖共享文件改动的子集）。

覆盖：任意目录启动解析、未识别项目不产生 execution、多项目状态隔离、
注册→发现→路径映射全链路、不同用户路径隔离。
"""
from __future__ import annotations

import json
import os
import subprocess

import project_resolver as pr
from project_register import apply_plan, build_plan
from repo_check import check_project_repos


def _git_repo(path):
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", "git@example.com:team/x.git"],
                   capture_output=True, check=True)
    return str(path)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _register(home, key, zid, repos, user="alice"):
    plan = build_plan(project_key=key, name=key, zentao_project_id=zid, user_id=user,
                      repos=repos, home=home)
    return apply_plan(plan, confirm=plan["fingerprint"])


# --------------------------------------------------------------- 任意目录启动
def test_registry_loadable_from_any_cwd(fake_home, tmp_path, monkeypatch):
    _write_json(os.path.join(str(fake_home), "config", "projects", "p-any.json"),
                {"project": {"key": "p-any", "zentao": {"project_id": 501}}})
    elsewhere = tmp_path / "some-other-project"
    os.makedirs(elsewhere)
    monkeypatch.chdir(elsewhere)  # 模拟从业务项目目录启动
    reg = pr.load_registry(str(fake_home))  # 显式 home（_home 解析由 31 测试覆盖）
    assert any(p.get("key") == "p-any" for p in reg)


# --------------------------------------------------------------- 未识别不产生 execution
def test_unregistered_creates_nothing(fake_home, tmp_path):
    _write_json(os.path.join(str(fake_home), "config", "projects", "p1.json"),
                {"project": {"key": "p1", "zentao": {"project_id": 1}}})
    r = pr.resolve_by_task({"project": "777"}, registry=pr.load_registry(str(fake_home)))
    assert r["status"] == "unregistered"
    assert not os.path.exists(os.path.join(str(fake_home), "execution"))
    assert not os.path.exists(str(tmp_path / "execution"))


# --------------------------------------------------------------- 多项目状态隔离
def test_execution_roots_isolated_per_project():
    a = os.path.join(os.sep, "wf", "execution", "proj-a", "5001")
    b = os.path.join(os.sep, "wf", "execution", "proj-b", "5001")
    cfg_a = {"execution_root": os.path.join(os.sep, "wf", "execution")}
    from _config import exec_root

    assert exec_root(cfg_a, "proj-a", "5001") != exec_root(cfg_a, "proj-b", "5001")
    assert exec_root(cfg_a, "proj-a", "5001").endswith(os.path.join("proj-a", "5001"))


# --------------------------------------------------------------- 全链路：注册→发现→路径
def test_full_chain_register_discover_paths(fake_home, tmp_path):
    backend = _git_repo(tmp_path / "ss-backend")
    frontend = _git_repo(tmp_path / "ss-ui")
    _register(fake_home, "smart-sanitation", "125", {
        "backend": {"path": backend, "role": "backend"},
        "frontend": {"path": frontend, "role": "frontend"},
    })

    r = pr.resolve_by_task({"project": "125"}, registry=pr.load_registry(str(fake_home)))
    assert r["status"] == "resolved" and r["project_key"] == "smart-sanitation"

    cfg = {"project": {"key": "smart-sanitation", "repositories": [
        {"key": "backend", "role": "backend"}, {"key": "frontend", "role": "frontend"}]}}
    paths = pr.repo_paths_for(cfg, "alice", home=str(fake_home))
    assert paths == {"backend": backend, "frontend": frontend}

    checks = check_project_repos({"key": "smart-sanitation", "repositories": cfg["project"]["repositories"]}, paths)
    assert all(c.ok for c in checks), [(c.repo_key, c.problems) for c in checks]


# --------------------------------------------------------------- 多项目并行隔离
def test_two_projects_same_task_isolated(fake_home, tmp_path):
    b1 = _git_repo(tmp_path / "a-backend")
    b2 = _git_repo(tmp_path / "b-backend")
    _register(fake_home, "proj-a", "101", {"backend": {"path": b1, "role": "backend"}})
    _register(fake_home, "proj-b", "102", {"backend": {"path": b2, "role": "backend"}})

    ra = pr.resolve_by_task({"project": "101"}, registry=pr.load_registry(str(fake_home)))
    rb = pr.resolve_by_task({"project": "102"}, registry=pr.load_registry(str(fake_home)))
    assert ra["project_key"] == "proj-a" and rb["project_key"] == "proj-b"

    cfg = {"project": {"key": "proj-a", "repositories": [{"key": "backend"}]}}
    assert pr.repo_paths_for(cfg, "alice", home=str(fake_home))["backend"] == b1
    cfg["project"]["key"] = "proj-b"
    assert pr.repo_paths_for(cfg, "alice", home=str(fake_home))["backend"] == b2


# --------------------------------------------------------------- 不同用户不同路径
def test_two_users_see_different_paths(fake_home, tmp_path):
    mine = _git_repo(tmp_path / "mine-backend")
    theirs = str(tmp_path / "their-backend")  # 不同机器上的路径
    plan = build_plan(project_key="shared-proj", name="共享项目", zentao_project_id="201",
                      user_id="alice", repos={"backend": {"path": mine, "role": "backend"}},
                      home=str(fake_home))
    apply_plan(plan, confirm=plan["fingerprint"])
    _write_json(os.path.join(str(fake_home), "config", "users", "bob.yaml"),
                {"user": {"id": "bob", "project_paths": {"shared-proj": {"backend": theirs}}}})

    cfg = {"project": {"key": "shared-proj", "repositories": [{"key": "backend"}]}}
    assert pr.repo_paths_for(cfg, "alice", home=str(fake_home))["backend"] == mine
    assert pr.repo_paths_for(cfg, "bob", home=str(fake_home))["backend"] == theirs
