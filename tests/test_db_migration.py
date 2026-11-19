# -*- coding: utf-8 -*-
"""SQLite schema 版本管理与迁移测试（Phase 0.5 §九 / 验收 §15.4）。

覆盖：新库初始化、旧库升级（记录保留）、重复迁移幂等、迁移失败回滚、
拒绝降级运行、迁移前备份。不删除、不重建库。
"""
from __future__ import annotations

import glob
import os
import sqlite3
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AM_DIR = os.path.join(REPO_ROOT, "agent-manager")
if AM_DIR not in sys.path:
    sys.path.insert(0, AM_DIR)

from state_manager import (  # noqa: E402
    MIGRATIONS,
    SCHEMA_VERSION,
    MigrationError,
    StateManager,
    migrate,
)


def _user_version(db: str) -> int:
    c = sqlite3.connect(db)
    v = c.execute("PRAGMA user_version").fetchone()[0]
    c.close()
    return v


def _tables(db: str) -> set:
    c = sqlite3.connect(db)
    rows = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    c.close()
    return {r[0] for r in rows}


def test_new_db_init(tmp_path):
    db = str(tmp_path / "new.db")
    sm = StateManager(db)
    assert _user_version(db) == SCHEMA_VERSION
    assert {"execution_runs", "agent_runs", "execution_events", "task_locks",
            "pending_writes", "node_dispatches"} <= _tables(db)
    assert sm.last_migration["to_version"] == SCHEMA_VERSION
    sm.close()


def test_old_db_upgrade_keeps_records(tmp_path):
    """旧库（user_version=0、已有数据）升级后记录保留（任务书 §九.2）。"""
    db = str(tmp_path / "old.db")
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE IF NOT EXISTS execution_runs (id INTEGER PRIMARY KEY,"
        " project_key TEXT, task_id TEXT);"
        "INSERT INTO execution_runs (project_key, task_id) VALUES ('p','T-old');"
    )
    c.commit()
    c.close()
    assert _user_version(db) == 0

    sm = StateManager(db)
    assert _user_version(db) == SCHEMA_VERSION
    c = sqlite3.connect(db)
    rows = c.execute("SELECT task_id FROM execution_runs").fetchall()
    c.close()
    assert ("T-old",) in rows
    sm.close()


def test_migration_idempotent(tmp_path):
    db = str(tmp_path / "idem.db")
    sm1 = StateManager(db)
    assert sm1.last_migration["executed"]  # 首次执行
    sm1.close()
    sm2 = StateManager(db)
    assert sm2.last_migration["executed"] == []  # 重复启动不重复迁移
    assert _user_version(db) == SCHEMA_VERSION
    sm2.close()


def test_migration_failure_rolls_back(tmp_path, monkeypatch):
    """迁移失败：版本不推进、DML 回滚、明确报错（任务书 §九.2）。

    注：sqlite3 legacy 事务模式下 DDL 隐式提交、无法回滚，DDL 恢复依赖
    迁移前备份——此处用 DML 验证事务回滚真实生效。
    """
    db = str(tmp_path / "fail.db")
    sm = StateManager(db)
    sm.close()
    backups_before = set(glob.glob(db + ".bak-*"))

    def bad_step(conn):
        conn.execute("INSERT INTO task_locks (project_key, task_id) VALUES ('x','y')")
        raise RuntimeError("boom")

    monkeypatch.setitem(MIGRATIONS, 2, bad_step)
    monkeypatch.setattr("state_manager.SCHEMA_VERSION", 2)
    with pytest.raises(MigrationError) as ei:
        StateManager(db)
    assert "回滚" in str(ei.value)
    assert _user_version(db) == SCHEMA_VERSION  # 版本未推进
    c = sqlite3.connect(db)
    rows = c.execute("SELECT project_key FROM task_locks").fetchall()
    c.close()
    assert rows == []  # 坏步骤的 DML 已回滚
    assert set(glob.glob(db + ".bak-*")) > backups_before  # 迁移前已生成新备份（可恢复）


def test_refuse_downgrade(tmp_path):
    db = str(tmp_path / "future.db")
    sm = StateManager(db)
    sm.close()
    c = sqlite3.connect(db)
    c.execute("PRAGMA user_version=99")
    c.commit()
    c.close()
    with pytest.raises(MigrationError) as ei:
        StateManager(db)
    assert "降级" in str(ei.value)
    assert _user_version(db) == 99  # 不修改库


def test_backup_created_before_migration(tmp_path):
    db = str(tmp_path / "bak.db")
    sm = StateManager(db)  # 建库（v0→v1 时已备份一次）
    sm.close()
    assert glob.glob(db + ".bak-*")  # 迁移前备份存在
