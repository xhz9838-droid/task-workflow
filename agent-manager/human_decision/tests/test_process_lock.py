# -*- coding: utf-8 -*-
"""统一进程锁回归：PID 复用、陈旧/损坏锁、单实例、释放身份。

覆盖任务要求的 10 个场景（PID 复用用模拟启动时间，不等待系统复用）。
"""
from __future__ import annotations

import json
import os
import threading
import time

import pytest

from human_decision import process_lock as pl
from human_decision.process_lock import ProcessLock


def _lock(path, **over):
    data = {
        "pid": os.getpid(),
        "started_at": pl.pid_started_at(os.getpid()),
        "created_at": "2026-11-23T00:00:00+08:00",
        "owner": "daemon",
        "token": "t-1",
    }
    data.update(over)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_acquire_and_release(tmp_path):
    p = tmp_path / "x.lock"
    lock = ProcessLock(str(p), "daemon")
    ok, _ = lock.acquire()
    assert ok and p.exists()
    assert lock.release() is True
    assert not p.exists()
    # 释放后可再次启动
    lock2 = ProcessLock(str(p), "daemon")
    assert lock2.acquire()[0] is True
    assert lock2.release() is True


def test_forced_termination_leaves_recoverable_stale_lock(tmp_path):
    import subprocess
    import sys

    p = tmp_path / "x.lock"
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = (
        "import sys,time\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "from human_decision.process_lock import ProcessLock\n"
        "l=ProcessLock(sys.argv[1],'daemon')\n"
        "print(l.acquire()[0], flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen([sys.executable, "-I", "-c", code, str(p), repo],
                            stdout=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline().strip()
        assert line == "True"
        proc.kill()
        proc.wait(timeout=10)
        for _ in range(50):
            if not pl.pid_alive(proc.pid):
                break
            time.sleep(0.1)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert ProcessLock(str(p), "daemon").acquire()[0] is True


def test_second_acquire_rejected(tmp_path):
    p = tmp_path / "x.lock"
    a = ProcessLock(str(p), "daemon")
    b = ProcessLock(str(p), "daemon")
    assert a.acquire()[0] is True
    ok, reason = b.acquire()
    assert ok is False and "存活实例" in reason


def test_stale_pid_recovered(tmp_path):
    p = tmp_path / "x.lock"
    _lock(p, pid=999999, started_at=time.time() - 100)
    ok, _ = ProcessLock(str(p), "daemon").acquire()
    assert ok is True


def test_pid_reused_by_other_process_recovered(tmp_path, monkeypatch):
    p = tmp_path / "x.lock"
    # 锁记录的启动时间与实际进程启动时间不一致 → PID 被复用
    _lock(p, started_at=time.time() - 10000)
    monkeypatch.setattr(pl, "pid_started_at", lambda pid: time.time())
    ok, _ = ProcessLock(str(p), "daemon").acquire()
    assert ok is True


def test_identity_unavailable_is_fail_safe(tmp_path):
    p = tmp_path / "x.lock"
    _lock(p, started_at=None)
    ok, reason = ProcessLock(str(p), "daemon").acquire()
    assert ok is False and "fail-safe" in reason


def test_corrupt_recent_not_stolen(tmp_path):
    p = tmp_path / "x.lock"
    p.write_text("not-json", encoding="utf-8")
    lock = ProcessLock(str(p), "daemon")
    ok, reason = lock.acquire()
    assert ok is False and "损坏" in reason
    assert lock.status().state == "corrupt"


def test_corrupt_old_recovered(tmp_path):
    p = tmp_path / "x.lock"
    p.write_text("not-json", encoding="utf-8")
    old = time.time() - 120
    os.utime(p, (old, old))
    assert ProcessLock(str(p), "daemon").acquire()[0] is True


def test_legacy_pid_lock_not_stolen(tmp_path):
    p = tmp_path / "x.lock"
    p.write_text(str(os.getpid()), encoding="utf-8")
    lock = ProcessLock(str(p), "daemon")
    assert lock.status().state == "unverified"
    assert lock.acquire()[0] is False


def test_release_wrong_owner_does_not_delete(tmp_path):
    p = tmp_path / "x.lock"
    owner = ProcessLock(str(p), "daemon")
    assert owner.acquire()[0] is True
    other = ProcessLock(str(p), "other")
    assert other.release() is False
    assert p.exists()
    assert owner.release() is True


def test_concurrent_acquire_single_winner(tmp_path):
    p = tmp_path / "x.lock"
    barrier = threading.Barrier(8)
    results = []

    def worker():
        barrier.wait()
        results.append(ProcessLock(str(p), "daemon").acquire()[0])

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1


def test_lock_has_identity_fields(tmp_path):
    p = tmp_path / "x.lock"
    assert ProcessLock(str(p), "supervisor").acquire()[0] is True
    data = json.loads(p.read_text(encoding="utf-8"))
    for k in ("pid", "started_at", "created_at", "owner", "token"):
        assert k in data
    assert data["owner"] == "supervisor"


def test_status_missing_and_running(tmp_path):
    p = tmp_path / "x.lock"
    assert ProcessLock(str(p), "daemon").status().state == "missing"
    lock = ProcessLock(str(p), "daemon")
    assert lock.acquire()[0] is True
    assert lock.status().state == "running"
