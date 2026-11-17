# -*- coding: utf-8 -*-
"""工作流根目录解析测试（scripts/_home.py）。

覆盖：从工作流仓库 / Java 后端项目 / Vue 前端项目 / 无关目录启动、
WORKFLOW_HOME 正确与不存在、根目录缺少必要配置、Skill 安装目录不被误判、
不同 CWD 定位同一根、状态目录隔离（不重复不错位）。
"""
import json
import os

import pytest

import _home
from _home import (
    INSTALL_RECORD_FILE,
    MARKERS,
    SOURCE_DEV_SOURCE,
    SOURCE_ENV,
    SOURCE_INSTALL_RECORD,
    SOURCE_PROBE,
    SOURCE_USER_CONFIG,
    HomeError,
    is_skill_install_dir,
    main,
    validate_home,
)

from wf_helpers import make_project_dir


# ---------------------------------------------------------- 从各类目录启动
def test_resolve_from_workflow_repo_root_dev_source(iso, fake_home):
    """从工作流仓库根启动：脚本所在仓库（开发源）通过校验即命中。"""
    home, source = iso(start=fake_home, script_home=fake_home)
    assert home == _home._norm(fake_home)
    assert source == SOURCE_DEV_SOURCE


def test_resolve_from_workflow_repo_root_by_probe(iso, fake_home):
    """从工作流仓库根启动（开发源候选不可用时）：向上探测命中自身。"""
    home, source = iso(start=fake_home)
    assert home == _home._norm(fake_home)
    assert source.startswith(SOURCE_PROBE)


def test_resolve_from_workflow_repo_subdir(iso, fake_home):
    """从工作流仓库子目录（execution 状态目录深处）启动：向上探测命中仓库根。"""
    deep = os.path.join(fake_home, "execution", "jeebootx", "3415", "logs")
    os.makedirs(deep)
    home, source = iso(start=deep)
    assert home == _home._norm(fake_home)
    assert source.startswith(SOURCE_PROBE)


def test_resolve_from_java_project_dir(iso, tmp_path, fake_home):
    """从 Java 后端项目目录启动：经 WORKFLOW_HOME 命中（项目目录本身不是工作流根）。"""
    java_dir = make_project_dir(tmp_path / "jeebootx", "jeebootx-sanitation")
    home, source = iso(start=java_dir, env={"WORKFLOW_HOME": fake_home})
    assert home == _home._norm(fake_home)
    assert source == SOURCE_ENV


def test_resolve_from_vue_project_dir_by_user_config(iso, tmp_path, fake_home):
    """从 Vue 前端项目目录启动：经用户级工作流配置命中。"""
    vue_dir = make_project_dir(tmp_path / "jeebootx", "jeebootx-ui")
    uc = tmp_path / "zentao-dev-workflow.json"
    uc.write_text(json.dumps({"workflow_home": fake_home}), encoding="utf-8")
    home, source = iso(start=vue_dir, user_cfg=str(uc))
    assert home == _home._norm(fake_home)
    assert source.startswith(SOURCE_USER_CONFIG)


def test_resolve_from_unrelated_dir_by_install_record(iso, tmp_path, fake_home):
    """从无关目录启动：经安装记录（install.sh 写入）命中。"""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    record = tmp_path / "zentao-dev-workflow.home"
    record.write_text(fake_home + "\n", encoding="utf-8")
    home, source = iso(start=elsewhere, record=str(record))
    assert home == _home._norm(fake_home)
    assert source.startswith(SOURCE_INSTALL_RECORD)


def test_install_record_msys_path_accepted(iso, tmp_path, fake_home):
    """Git Bash 写入的 MSYS 路径（/d/...）作为安装记录也能被 Windows Python 解析。"""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    msys = "/" + fake_home[0].lower() + fake_home[2:].replace("\\", "/")
    record = tmp_path / "zentao-dev-workflow.home"
    record.write_text(msys + "\n", encoding="utf-8")
    home, source = iso(start=elsewhere, record=str(record))
    assert home == _home._norm(fake_home)
    assert source.startswith(SOURCE_INSTALL_RECORD)


def test_same_home_from_different_cwds(iso, tmp_path, fake_home):
    """不同 CWD 最终定位到同一个工作流根（状态目录不因启动目录而分裂）。"""
    java_dir = make_project_dir(tmp_path / "jeebootx", "jeebootx-sanitation")
    vue_dir = make_project_dir(tmp_path / "jeebootx", "jeebootx-ui")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    homes = {
        iso(start=fake_home, env={"WORKFLOW_HOME": fake_home})[0],
        iso(start=java_dir, env={"WORKFLOW_HOME": fake_home})[0],
        iso(start=vue_dir, env={"WORKFLOW_HOME": fake_home})[0],
        iso(start=elsewhere, env={"WORKFLOW_HOME": fake_home})[0],
    }
    assert homes == {_home._norm(fake_home)}


# ---------------------------------------------------------- WORKFLOW_HOME 语义
def test_workflow_home_env_correct(iso, fake_home):
    """WORKFLOW_HOME 正确：最高优先级直接命中。"""
    home, source = iso(env={"WORKFLOW_HOME": fake_home})
    assert home == _home._norm(fake_home)
    assert source == SOURCE_ENV


def test_workflow_home_env_missing_falls_through(iso, tmp_path, fake_home):
    """WORKFLOW_HOME 不存在（未设置）：回落到安装记录，而不是报错。"""
    record = tmp_path / "zentao-dev-workflow.home"
    record.write_text(fake_home, encoding="utf-8")
    home, source = iso(record=str(record))
    assert home == _home._norm(fake_home)
    assert source.startswith(SOURCE_INSTALL_RECORD)


def test_workflow_home_env_invalid_raises(iso, tmp_path):
    """WORKFLOW_HOME 指向无效目录：明确报错，不静默回落到其他来源。"""
    record = tmp_path / "zentao-dev-workflow.home"
    record.write_text(str(tmp_path / "real-home"), encoding="utf-8")
    with pytest.raises(HomeError):
        iso(env={"WORKFLOW_HOME": str(tmp_path / "ghost")}, record=str(record))


# ---------------------------------------------------------- 校验与误判防护
def test_home_missing_required_config(tmp_path):
    """工作流根缺少必要配置：只有 config/workflow.yaml 或只有 scripts/_config.py 都不通过。"""
    half1 = tmp_path / "half1"
    (half1 / "config").mkdir(parents=True)
    (half1 / "config" / "workflow.yaml").write_text("x: 1\n", encoding="utf-8")
    half2 = tmp_path / "half2"
    (half2 / "scripts").mkdir(parents=True)
    (half2 / "scripts" / "_config.py").write_text("# stub\n", encoding="utf-8")
    for half in (half1, half2):
        problems = validate_home(str(half))
        assert any("缺少必要文件" in p for p in problems)
    with pytest.raises(HomeError):
        _home.resolve_workflow_home(
            start=str(half1),
            env={},
            user_config_file=str(tmp_path / "absent.json"),
            install_record_file=str(tmp_path / "absent.home"),
            script_home=str(tmp_path / "absent-skill"),
        )


def test_home_missing_required_config_cli_exit_code(tmp_path):
    half = tmp_path / "half"
    (half / "config").mkdir(parents=True)
    (half / "config" / "workflow.yaml").write_text("x: 1\n", encoding="utf-8")
    assert main(["pytest", "--check", "--path", str(half)]) == 3


def test_skill_install_dir_never_home(iso, tmp_path, fake_home):
    """Skill 安装目录不包含 config/execution：不得被当作工作流根。"""
    skill_dir = tmp_path / ".claude" / "skills" / "zentao-dev-workflow"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "scripts" / "_home.py").write_text("# boot\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    assert is_skill_install_dir(str(skill_dir))
    # 即使把标记文件放进去，Skill 安装目录也永远不是工作流根
    (skill_dir / "config").mkdir()
    (skill_dir / "config" / "workflow.yaml").write_text("x: 1\n", encoding="utf-8")
    (skill_dir / "scripts" / "_config.py").write_text("# stub\n", encoding="utf-8")
    assert any("Skill 安装目录" in p for p in validate_home(str(skill_dir)))
    # 从 Skill 安装目录启动且无其他来源：报错，而不是误判 Skill 安装目录
    with pytest.raises(HomeError):
        iso(start=skill_dir, script_home=skill_dir)
    # 有安装记录时：照常定位到工作流仓库
    record = tmp_path / "zentao-dev-workflow.home"
    record.write_text(fake_home, encoding="utf-8")
    home, source = iso(start=skill_dir, script_home=skill_dir, record=str(record))
    assert home == _home._norm(fake_home)
    assert source.startswith(SOURCE_INSTALL_RECORD)


def test_project_dir_mistaken_never(iso, tmp_path, fake_home):
    """业务项目目录（Java/Vue）不得被误判为工作流根。"""
    java_dir = make_project_dir(tmp_path / "jeebootx", "jeebootx-sanitation")
    assert validate_home(java_dir)
    with pytest.raises(HomeError):
        iso(start=java_dir)  # 无任何来源时：报错，而不是误判项目目录


# ---------------------------------------------------------- 状态隔离
def test_state_dirs_isolated_by_project_and_task(tmp_path, fake_home):
    """execution/{project}/{task} 按项目任务隔离、路径确定；不覆盖已有状态目录。"""
    import _config

    cfg = {"execution_root": os.path.join(fake_home, "execution")}
    p_a = _config.exec_root(cfg, "jeebootx", "3415")
    p_b = _config.exec_root(cfg, "demo-react", "3415")
    assert p_a != p_b
    assert p_a == _config.exec_root(cfg, "jeebootx", "3415")  # 确定性：不产生重复目录
    assert p_a == os.path.normpath(os.path.join(cfg["execution_root"], "jeebootx", "3415"))
    # 已有任务状态不被后续任务的目录创建覆盖
    os.makedirs(p_a)
    sentinel = os.path.join(p_a, "run-state.json")
    with open(sentinel, "w", encoding="utf-8") as f:
        f.write("{}")
    os.makedirs(p_b, exist_ok=True)
    with open(sentinel, encoding="utf-8") as f:
        assert f.read() == "{}"


def test_install_record_default_path():
    assert INSTALL_RECORD_FILE.replace("\\", "/").endswith(".claude/zentao-dev-workflow.home")
    assert MARKERS == ("config/workflow.yaml", "scripts/_config.py")
