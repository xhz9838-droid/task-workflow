# -*- coding: utf-8 -*-
"""配置诊断回归测试：
    - ConfigError 错误码可区分（PROJECT/USER/ENV/PARSE）
    - show 脱敏真正生效（含嵌套与 URL 内嵌凭据）
    - project_register --repo 解析兼容 Windows 盘符与 https 远程地址
"""
from __future__ import annotations

import os
import sys

import pytest

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, _SCRIPTS)

import _config  # noqa: E402
from project_register import _parse_repo_spec  # noqa: E402


def _home(tmp_path):
    root = tmp_path / "wf"
    (root / "config" / "projects").mkdir(parents=True)
    (root / "config" / "users").mkdir(parents=True)
    (root / "config" / "adapters").mkdir(parents=True)
    (root / "config" / "workflow.yaml").write_text("version: 1\n", encoding="utf-8")
    return root


def _patch_root(monkeypatch, root):
    monkeypatch.setattr(_config, "workflow_root", lambda: str(root))


# --------------------------------------------------------------- error codes
def test_project_config_not_found_code(tmp_path, monkeypatch):
    _patch_root(monkeypatch, _home(tmp_path))
    with pytest.raises(_config.ConfigError) as ei:
        _config.load_config("nope", strict=True)
    assert ei.value.code == "PROJECT_CONFIG_NOT_FOUND"
    assert "nope.yaml" in str(ei.value)


def test_user_config_not_found_code(tmp_path, monkeypatch):
    root = _home(tmp_path)
    (root / "config" / "projects" / "p.yaml").write_text("project:\n  key: p\n", encoding="utf-8")
    _patch_root(monkeypatch, root)
    with pytest.raises(_config.ConfigError) as ei:
        _config.load_config("p", "ghost", strict=True)
    assert ei.value.code == "USER_CONFIG_NOT_FOUND"


def test_env_variable_missing_code(tmp_path, monkeypatch):
    root = _home(tmp_path)
    (root / "config" / "projects" / "p.yaml").write_text(
        "project:\n  key: p\n  root: \"${SURELY_NOT_DEFINED_VAR}\"\n", encoding="utf-8")
    _patch_root(monkeypatch, root)
    monkeypatch.delenv("SURELY_NOT_DEFINED_VAR", raising=False)
    with pytest.raises(_config.ConfigError) as ei:
        _config.load_config("p", strict=True)
    assert ei.value.code == "ENV_VARIABLE_MISSING"
    assert "SURELY_NOT_DEFINED_VAR" in str(ei.value)


def test_parse_error_code(tmp_path, monkeypatch):
    root = _home(tmp_path)
    (root / "config" / "projects" / "bad.yaml").write_text("project: [unclosed\n", encoding="utf-8")
    _patch_root(monkeypatch, root)
    with pytest.raises(_config.ConfigError) as ei:
        _config.load_config("bad", strict=True)
    assert ei.value.code == "CONFIG_PARSE_ERROR"


# --------------------------------------------------------------- redaction
def test_redact_masks_secrets_and_url_userinfo():
    raw = {
        "token": "abc",
        "nested": {"password": "p", "api_key": "k"},
        "items": [{"secret": "s"}],
        "url": "https://user:pass@host/path",
        "safe": "ok",
    }
    out = _config._redact(raw)
    assert out["token"] == "***"
    assert out["nested"]["password"] == "***"
    assert out["nested"]["api_key"] == "***"
    assert out["items"][0]["secret"] == "***"
    assert out["url"] == "https://user:***@host/path"
    assert out["safe"] == "ok"


# --------------------------------------------------------------- register parser
def test_repo_spec_windows_drive_without_role():
    key, spec = _parse_repo_spec("b=D:/WorkSpace/x")
    assert key == "b" and spec["path"] == "D:/WorkSpace/x" and spec["role"] == ""


def test_repo_spec_windows_drive_with_role_and_https_remote():
    key, spec = _parse_repo_spec("b=D:/WorkSpace/x:backend:https://example/repo.git")
    assert spec["path"] == "D:/WorkSpace/x"
    assert spec["role"] == "backend"
    assert spec["remote_url"] == "https://example/repo.git"


def test_repo_spec_posix_path():
    key, spec = _parse_repo_spec("b=/srv/x:frontend")
    assert spec["path"] == "/srv/x" and spec["role"] == "frontend"
