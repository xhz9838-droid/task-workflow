# -*- coding: utf-8 -*-
"""HITL daemon 单消费者与锁恢复回归。"""
from __future__ import annotations

import os
import sys

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "human_decision")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from human_decision import cli  # noqa: E402


def test_stale_lock_is_taken_over(tmp_path):
    lock = tmp_path / "hitl-daemon.lock"
    lock.write_text("0", encoding="utf-8")          # 0 = 必然不存活
    assert cli._acquire_daemon_lock(str(lock)) is True
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())
    cli._release_daemon_lock(str(lock))
    assert not lock.exists()


def test_live_lock_rejects_second_consumer(tmp_path):
    lock = tmp_path / "hitl-daemon.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    assert cli._acquire_daemon_lock(str(lock)) is False
    # 不覆盖存活实例的锁
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_release_only_own_lock(tmp_path):
    lock = tmp_path / "hitl-daemon.lock"
    lock.write_text("999999", encoding="utf-8")
    cli._release_daemon_lock(str(lock))
    assert lock.exists()  # 非本进程锁不得删除
