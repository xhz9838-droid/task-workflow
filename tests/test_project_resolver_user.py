# -*- coding: utf-8 -*-
"""project_resolver 用户身份解析测试：Windows Administrator ≠ xuhongzu 场景。

覆盖：
- current_user_id() 解析链优先级
- whoami CLI 子命令
- --user 为空时不在 CLI 层传 OS 用户名
- project_register _try_resolve_user 回退
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

import pytest

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, _SCRIPTS)


# --------------------------------------------------------------- current_user_id 解析链
_REAL_CONFIG = os.path.expanduser("~/.claude/zentao-dev-workflow.json")


@pytest.fixture(autouse=True)
def _clear_env_and_config(monkeypatch):
    """每个测试前清除环境变量和用户配置。"""
    monkeypatch.delenv("WORKFLOW_USER_ID", raising=False)
    # 仅屏蔽真实用户级 JSON（不影响测试内 tmp_path 创建的假 JSON）
    _real_exists = os.path.exists

    def _patched_exists(p):
        if p == _REAL_CONFIG:
            return False
        return _real_exists(p)

    monkeypatch.setattr(os.path, "exists", _patched_exists)


def test_current_user_id_explicit_priority():
    """显式传入的 user_id 优先级最高。"""
    from project_resolver import current_user_id
    uid = current_user_id("xuhongzu")
    assert uid == "xuhongzu"
    # 即使传入的是 OS 用户名也应原样返回（调用方责任，不在此过滤）
    uid2 = current_user_id("Administrator")
    assert uid2 == "Administrator"


def test_current_user_id_from_env(monkeypatch):
    """WORKFLOW_USER_ID 环境变量次优先。"""
    monkeypatch.setenv("WORKFLOW_USER_ID", "xuhongzu")
    from project_resolver import current_user_id, _user_id_source
    uid = current_user_id()
    assert uid == "xuhongzu"
    assert _user_id_source() == "env:WORKFLOW_USER_ID"


def test_current_user_id_from_json(monkeypatch, tmp_path):
    """~/.claude/zentao-dev-workflow.json 作为最后回退。"""
    # 准备假 JSON
    cfg_dir = tmp_path / ".claude"
    cfg_dir.mkdir(parents=True)
    with open(cfg_dir / "zentao-dev-workflow.json", "w") as f:
        json.dump({"user_id": "xuhongzu"}, f)
    monkeypatch.setattr(os.path, "expanduser",
                       lambda p: str(cfg_dir / "zentao-dev-workflow.json")
                       if "zentao-dev-workflow.json" in p else p)
    from project_resolver import current_user_id, _user_id_source
    uid = current_user_id()
    assert uid == "xuhongzu"
    assert "config:" in _user_id_source()


def test_current_user_id_raises_when_nothing_configured():
    """无任何配置时明确抛出 ResolveError，不猜测。"""
    from project_resolver import current_user_id, ResolveError
    with pytest.raises(ResolveError, match="无法确定当前用户"):
        current_user_id()


# --------------------------------------------------------------- whoami CLI 子命令
def _run_cli(*args):
    from project_resolver import main
    import io
    buf = io.StringIO()
    try:
        sys.stdout = buf
        exit_code = main(list(args))
    finally:
        sys.stdout = sys.__stdout__
    return exit_code, buf.getvalue()


def test_cli_whoami_from_env(monkeypatch):
    """whoami 子命令从环境变量解析。"""
    monkeypatch.setenv("WORKFLOW_USER_ID", "xuhongzu")
    code, out = _run_cli("whoami")
    assert code == 0
    data = json.loads(out)
    assert data["user_id"] == "xuhongzu"
    assert data["source"] == "env:WORKFLOW_USER_ID"


def test_cli_whoami_error_when_nothing(monkeypatch):
    """whoami 未配置时报错。"""
    code, out = _run_cli("whoami")
    assert code != 0
    data = json.loads(out)
    assert "error" in data


def test_cli_context_without_user_resolves_from_env(monkeypatch, tmp_path):
    """context --project 不带 --user 时自动从环境解析。"""
    monkeypatch.setenv("WORKFLOW_USER_ID", "xuhongzu")
    # 模拟项目存在
    monkeypatch.setattr("project_resolver.load_config",
                       lambda project_key, user_id, strict: {"project": {"key": project_key}})
    code, out = _run_cli("context", "--project", "ai-platfrom")
    assert code == 0


# --------------------------------------------------------------- project_register _try_resolve_user
def test_try_resolve_user_from_env(monkeypatch):
    """_try_resolve_user 从环境解析成功。"""
    monkeypatch.setenv("WORKFLOW_USER_ID", "xuhongzu")
    from project_register import _try_resolve_user
    assert _try_resolve_user() == "xuhongzu"


def test_try_resolve_user_empty_when_nothing(monkeypatch):
    """_try_resolve_user 无配置时返回空字符串（--user 为可选参数）。"""
    from project_register import _try_resolve_user
    assert _try_resolve_user() == ""