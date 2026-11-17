# -*- coding: utf-8 -*-
"""项目解析测试（任务 §九·项目解析测试）。仅 tmp 假目录，不读真实机器状态。"""
from __future__ import annotations

import os

import pytest

import project_resolver as pr
# 复用 tests/conftest.py 的 fake_home（最小工作流根构造，永不读真实机器状态）


def _write_project(home, key, block: dict):
    import json

    pdir = os.path.join(str(home), "config", "projects")
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, key + ".yaml"), "w", encoding="utf-8") as f:
        # JSON 是 YAML 子集：测试夹具免装 PyYAML 也能被 _read_yaml 读取
        json.dump({"project": block}, f, ensure_ascii=False)


def _write_user(home, uid, data: dict):
    import json

    udir = os.path.join(str(home), "config", "users")
    os.makedirs(udir, exist_ok=True)
    with open(os.path.join(udir, uid + ".yaml"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


@pytest.fixture
def home(fake_home):
    _write_project(fake_home, "smart-sanitation", {
        "key": "smart-sanitation", "name": "智慧环卫管理平台",
        "zentao": {"project_id": 125, "product_ids": [7]},
        "repositories": [{"key": "backend", "path": "C:/ws/ss-backend", "role": "backend"}],
    })
    _write_project(fake_home, "demo-react", {
        "key": "demo-react", "name": "Demo React App",
        "zentao_project": "88",
        "repositories": [{"key": "api", "path": "C:/ws/demo-api", "role": "backend"}],
    })
    return fake_home


def _reg(home):
    return pr.load_registry(home)


# --------------------------------------------------------------- 匹配裁决
def test_resolved_unique_project_id(home):
    r = pr.resolve_by_task({"project": "125"}, registry=_reg(home))
    assert r["status"] == "resolved" and r["project_key"] == "smart-sanitation"


def test_resolved_via_list_zentao_project(home):
    r = pr.resolve_by_task({"project": "88"}, registry=_reg(home))
    assert r["status"] == "resolved" and r["project_key"] == "demo-react"


def test_unregistered(home):
    r = pr.resolve_by_task({"project": "999"}, registry=_reg(home))
    assert r["status"] == "unregistered"
    assert "register" in r["reason"] or "注册" in r["reason"]


def test_ambiguous_multiple_matches(home):
    _write_project(home, "other-ss", {
        "key": "other-ss", "name": "另一个环卫",
        "zentao": {"project_id": 125},
        "repositories": [],
    })
    r = pr.resolve_by_task({"project": "125"}, registry=_reg(home))
    assert r["status"] == "ambiguous"
    assert len(r["candidates"]) == 2


def test_name_only_match_needs_confirm(home):
    r = pr.resolve_by_task({"projectName": "智慧环卫管理平台"}, registry=_reg(home))
    assert r["status"] == "needs_confirm"
    assert r["candidates"][0]["tier"] == "text"


def test_product_id_aux_match(home):
    r = pr.resolve_by_task({"project": "555", "product_ids": ["7"]}, registry=_reg(home))
    assert r["status"] == "resolved" and r["project_key"] == "smart-sanitation"
    assert r["candidates"][0]["tier"] == "product"


def test_disabled_project_not_matched(home):
    _write_project(home, "old-ss", {
        "key": "old-ss", "name": "旧环卫", "enabled": False,
        "zentao": {"project_id": 300}, "repositories": [],
    })
    r = pr.resolve_by_task({"project": "300"}, registry=_reg(home))
    assert r["status"] == "disabled"


def test_missing_refs_no_match(home):
    r = pr.resolve_by_task({}, registry=_reg(home))
    assert r["status"] == "unregistered"


# --------------------------------------------------------------- 用户路径映射
def test_user_paths_override(home):
    _write_user(home, "alice", {"user": {"id": "alice", "project_paths": {
        "smart-sanitation": {"backend": "D:/alice/ss-backend"}}}})
    cfg = {"project": {"key": "smart-sanitation", "repositories": [
        {"key": "backend", "path": "C:/ws/ss-backend"}]}}
    paths = pr.repo_paths_for(cfg, "alice", home=home)
    assert paths["backend"] == "D:/alice/ss-backend"


def test_user_without_mapping_falls_back(home):
    _write_user(home, "bob", {"user": {"id": "bob"}})
    cfg = {"project": {"key": "smart-sanitation", "repositories": [
        {"key": "backend", "path": "C:/ws/ss-backend"}]}}
    paths = pr.repo_paths_for(cfg, "bob", home=home)
    assert paths["backend"] == "C:/ws/ss-backend"


def test_different_users_different_paths(home):
    _write_user(home, "alice", {"user": {"project_paths": {"p1": {"r": "D:/a/r"}}}})
    _write_user(home, "bob", {"user": {"project_paths": {"p1": {"r": "D:/b/r"}}}})
    cfg = {"project": {"key": "p1", "repositories": [{"key": "r", "path": "C:/x"}]}}
    assert pr.repo_paths_for(cfg, "alice", home=home)["r"] == "D:/a/r"
    assert pr.repo_paths_for(cfg, "bob", home=home)["r"] == "D:/b/r"


def test_load_user_paths_missing_file(home):
    assert pr.load_user_paths("nobody", home=home) == {}


# --------------------------------------------------------------- 当前用户解析
def test_current_user_explicit_and_env(monkeypatch):
    assert pr.current_user_id("alice") == "alice"
    monkeypatch.setenv("WORKFLOW_USER_ID", "envuser")
    assert pr.current_user_id() == "envuser"


def test_current_user_unknown_raises(monkeypatch):
    monkeypatch.delenv("WORKFLOW_USER_ID", raising=False)
    monkeypatch.setattr(os.path, "expanduser", lambda p: "/nonexistent/" + p.replace("~", ""))
    with pytest.raises(pr.ResolveError):
        pr.current_user_id()


# --------------------------------------------------------------- 注册表
def test_load_registry_skips_example(home):
    _write_project(home, "project.example", {"key": "${PROJECT_KEY}"})
    reg = _reg(home)
    keys = {p.get("key") for p in reg}
    assert "${PROJECT_KEY}" not in keys
    assert "smart-sanitation" in keys


def test_resolve_by_key_missing(monkeypatch):
    monkeypatch.setattr(pr, "load_registry", lambda *a, **k: [])
    with pytest.raises(pr.ResolveError):
        pr.resolve_by_key("nope-config")
