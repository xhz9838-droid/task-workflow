# -*- coding: utf-8 -*-
"""pytest fixtures：隔离的解析调用器（永不读取真实机器状态）。"""
import pytest

from wf_helpers import make_home  # noqa: F401  （re-export 给测试用）


@pytest.fixture
def fake_home(tmp_path):
    return make_home(tmp_path / "task-workflow")


@pytest.fixture
def iso(tmp_path):
    """隔离的 resolve_workflow_home 调用器。

    固定传入不存在的用户级配置 / 安装记录 / 开发源候选，起点默认 tmp_path，
    确保测试永不读取真实机器状态（真实 ~/.claude、真实 CWD）。
    """
    import _home

    absent_user_cfg = str(tmp_path / "absent-user.json")
    absent_record = str(tmp_path / "absent.home")
    absent_script_home = str(tmp_path / "absent-skill-dir")

    def _resolve(start=None, env=None, user_cfg=None, record=None, script_home=None):
        return _home.resolve_workflow_home(
            start=str(start) if start is not None else str(tmp_path),
            env={} if env is None else env,
            user_config_file=user_cfg if user_cfg is not None else absent_user_cfg,
            install_record_file=record if record is not None else absent_record,
            script_home=script_home if script_home is not None else absent_script_home,
        )

    return _resolve
