# -*- coding: utf-8 -*-
"""zt.py 项目发现子命令测试（Mock 客户端，不访问真实禅道）。"""
from __future__ import annotations

import io
import json

import pytest

import zt


class FakeClient:
    """Mock ZenTaoClient：只读接口按预设返回。"""

    def __init__(self, task=None, projects=None, me="xuhongzu"):
        self.api_prefix = "/api.php/v1"
        self._task = task or {}
        self._projects = projects or []
        self._me = me

    def whoami(self):
        return {"profile": {"account": self._me}}

    def task_detail(self, task_id):
        return dict(self._task)

    def _auth_headers(self):
        return {"Token": "fake"}

    def _request(self, path, method="GET", headers=None, body=None, timeout=30):
        if path.endswith("/projects"):
            return {"projects": self._projects, "total": len(self._projects)}, 200
        raise AssertionError("unexpected request: %s" % path)


def _run(fn, args, capsys):
    rc = fn(args)
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_projects_list(monkeypatch, capsys):
    fake = FakeClient(projects=[
        {"id": 125, "name": "智慧环卫管理平台", "status": "doing", "type": "project"},
        {"id": 88, "name": "Demo", "status": "closed", "type": "project"},
    ])
    monkeypatch.setattr(zt, "_client", lambda: fake)
    rc, out = _run(zt.cmd_projects, type("A", (), {})(), capsys)
    assert rc == 0 and out["count"] == 2
    assert out["projects"][0]["id"] == 125


def test_project_attribution(monkeypatch, capsys):
    fake = FakeClient(
        task={"id": 5001, "name": "任务A", "status": "wait", "project": 125,
              "execution": 115, "product": 7, "assignedTo": "xuhongzu"},
        projects=[{"id": 125, "name": "智慧环卫管理平台", "status": "doing"}],
    )
    monkeypatch.setattr(zt, "_client", lambda: fake)
    rc, out = _run(zt.cmd_project, type("A", (), {"task": "5001"})(), capsys)
    assert rc == 0
    assert out["project"] == "125"
    assert out["projectName"] == "智慧环卫管理平台"
    assert out["product_ids"] == ["7"]
    assert out["assignee"] == "xuhongzu"


def test_project_name_lookup_missing_is_not_blocking(monkeypatch, capsys):
    fake = FakeClient(task={"id": 9, "name": "t", "project": 404, "assignedTo": "xuhongzu"}, projects=[])
    monkeypatch.setattr(zt, "_client", lambda: fake)
    rc, out = _run(zt.cmd_project, type("A", (), {"task": "9"})(), capsys)
    assert rc == 0 and out["projectName"] == ""


def test_non_owner_task_rejected(monkeypatch, capsys):
    fake = FakeClient(task={"id": 9, "name": "t", "project": 1, "assignedTo": "someoneelse"},
                      me="xuhongzu")
    monkeypatch.setattr(zt, "_client", lambda: fake)
    with pytest.raises(SystemExit):
        zt.cmd_project(type("A", (), {"task": "9"})())
