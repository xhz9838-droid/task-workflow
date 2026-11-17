# -*- coding: utf-8 -*-
"""配置加载器根目录统一测试（scripts/_config.py）。

覆盖：配置路径/执行状态/审计路径统一使用定位后的工作流根、项目配置缺失明确报错、
.env 的 WORKFLOW_HOME 与解析结果冲突/一致两种语义。
"""
import os

import pytest

import _config
from _config import ConfigError, exec_root, load_config, workflow_root


@pytest.fixture(autouse=True)
def _reset_root_cache(monkeypatch):
    monkeypatch.setattr(_config, "_root_cache", None)
    yield
    _config._root_cache = None


@pytest.fixture
def home(fake_home, monkeypatch):
    """带项目/人员配置的假工作流根，并以 WORKFLOW_HOME 定位。"""
    proj = os.path.join(fake_home, "config", "projects", "x.yaml")
    with open(proj, "w", encoding="utf-8") as f:
        f.write("project:\n  key: x\n  name: x\n")
    user = os.path.join(fake_home, "config", "users", "u.yaml")
    os.makedirs(os.path.dirname(user), exist_ok=True)
    with open(user, "w", encoding="utf-8") as f:
        f.write("user:\n  id: u\n")
    monkeypatch.setenv("WORKFLOW_HOME", fake_home)
    return fake_home


def test_load_config_uses_located_root(home):
    cfg = load_config("x", "u")
    assert cfg["_root"] == _config._norm_path(home)
    assert workflow_root() == _config._norm_path(home)
    # ${WORKFLOW_HOME} 从定位后的根替换，不依赖 .env
    assert os.path.normpath(cfg["execution_root"]) == os.path.join(_config._norm_path(home), "execution")


def test_exec_root_under_located_root(home):
    cfg = load_config("x", "u")
    path = exec_root(cfg, "x", "3415")
    assert path == os.path.join(_config._norm_path(home), "execution", "x", "3415")


def test_project_config_missing_raises(home):
    with pytest.raises(ConfigError) as e:
        load_config("nope", "u")
    assert "项目配置不存在" in str(e.value)


def test_user_config_missing_raises(home):
    with pytest.raises(ConfigError) as e:
        load_config("x", "nope")
    assert "人员配置不存在" in str(e.value)


def test_dotenv_workflow_home_conflict_raises(home):
    """.env 声明的 WORKFLOW_HOME 与解析结果不一致 → 明确报错（防状态目录分裂）。"""
    with open(os.path.join(home, ".env"), "w", encoding="utf-8") as f:
        f.write("WORKFLOW_HOME=D:/somewhere/else\n")
    with pytest.raises(ConfigError) as e:
        load_config("x", "u")
    assert "WORKFLOW_HOME 冲突" in str(e.value)


def test_dotenv_workflow_home_consistent_ok(home):
    """.env 声明的 WORKFLOW_HOME 与解析结果一致（不同拼写）→ 正常。"""
    spelled = home.replace("/", "\\") if "/" in home else home
    with open(os.path.join(home, ".env"), "w", encoding="utf-8") as f:
        f.write("WORKFLOW_HOME=%s\n" % spelled)
    cfg = load_config("x", "u")
    assert cfg["_root"] == _config._norm_path(home)
