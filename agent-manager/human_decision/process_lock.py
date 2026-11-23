# -*- coding: utf-8 -*-
"""统一的 HITL 进程锁（daemon / supervisor 共用）。

锁文件为 JSON：pid / started_at / created_at / owner / token。
有效性判定：
    - PID 存活；
    - 若锁记录与当前进程启动时间都能取得，则必须一致（防 PID 复用）；
    - 身份信息缺失时**不抢锁**（fail-safe），避免误杀仍在运行的实例。
陈旧锁通过“改名隔离”处理，绝不直接删除可能属于存活实例的锁。
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from typing import Optional

CORRUPT_GRACE_SECONDS = 30


# --------------------------------------------------------------- 进程探测
def pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            try:
                code = wintypes.DWORD()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return code.value == 259  # STILL_ACTIVE
                return False
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def pid_started_at(pid: int) -> Optional[float]:
    """进程启动时间（epoch 秒）。无法可靠取得时返回 None（调用方不得据此抢锁）。"""
    if not pid_alive(pid):
        return None
    try:
        if os.name == "nt":
            return _win_started_at(pid)
        return _posix_started_at(pid)
    except Exception:
        return None


def _win_started_at(pid: int) -> Optional[float]:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        ok = kernel32.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited),
            ctypes.byref(kernel), ctypes.byref(user))
        if not ok:
            return None
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return ticks / 10_000_000.0 - 11644473600.0  # FILETIME -> Unix epoch
    finally:
        kernel32.CloseHandle(handle)


def _posix_started_at(pid: int) -> Optional[float]:
    # Linux: /proc/<pid>/stat 第 22 字段（启动后的 clock ticks）
    stat = f"/proc/{pid}/stat"
    if os.path.exists(stat):
        with open(stat, encoding="utf-8", errors="replace") as f:
            parts = f.read().split()
        if len(parts) > 21:
            return float(parts[21]) / os.sysconf("SC_CLK_TCK")
    # macOS/BSD: ps lstart
    try:
        p = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                           capture_output=True, text=True, timeout=5)
        if p.returncode == 0 and p.stdout.strip():
            import datetime as _dt
            return _dt.datetime.strptime(
                p.stdout.strip(), "%a %b %d %H:%M:%S %Y").timestamp()
    except Exception:
        pass
    return None


# --------------------------------------------------------------- 锁
@dataclass
class LockStatus:
    state: str          # running | stale | corrupt | missing | unverified
    info: dict
    reason: str = ""


class ProcessLock:
    def __init__(self, path: str, owner: str):
        self.path = path
        self.owner = owner
        self.token = ""
        self._held = False

    # -------------------------------------------------- 读
    def read(self) -> tuple[Optional[dict], str]:
        if not os.path.exists(self.path):
            return None, "missing"
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = f.read()
            if raw.strip().isdigit():
                return {"pid": int(raw.strip()), "legacy": True}, "legacy"
            data = json.loads(raw)
            if not isinstance(data, dict) or not data.get("pid"):
                raise ValueError("invalid lock payload")
            return data, "ok"
        except Exception as e:
            return None, f"corrupt: {type(e).__name__}"

    def status(self) -> LockStatus:
        data, state = self.read()
        if state == "missing":
            return LockStatus("missing", {}, "锁文件不存在")
        if data is None:
            age = _age(self.path)
            if age is not None and age > CORRUPT_GRACE_SECONDS:
                return LockStatus("stale", {}, "锁信息损坏且已过期")
            return LockStatus("corrupt", {}, "锁信息损坏（近期，等待持有者写入）")
        pid = int(data.get("pid") or 0)
        if not pid_alive(pid):
            return LockStatus("stale", data, f"PID {pid} 不存在")
        if data.get("legacy"):
            return LockStatus("unverified", data,
                              "旧版 PID 锁：无法验证启动时间（fail-safe）")
        recorded = data.get("started_at")
        current = pid_started_at(pid)
        if recorded is not None and current is not None:
            if abs(float(recorded) - float(current)) > 1.0:
                return LockStatus("stale", data,
                                  f"PID {pid} 已被复用（启动时间不一致）")
            return LockStatus("running", data, "PID 与启动时间一致")
        # 任何一方缺失 → 不抢锁，明确标记未验证
        return LockStatus("unverified", data,
                          "PID 存活但无法验证启动时间（fail-safe）")

    # -------------------------------------------------- 获取
    def acquire(self) -> tuple[bool, str]:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        for _ in range(3):
            payload = {
                "pid": os.getpid(),
                "started_at": pid_started_at(os.getpid()),
                "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                "owner": self.owner,
                "token": uuid.uuid4().hex,
            }
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                self.token = payload["token"]
                self._held = True
                return True, "acquired"
            except FileExistsError:
                st = self.status()
                if st.state == "running":
                    return False, f"已有存活实例 pid={st.info.get('pid')} owner={st.info.get('owner')}"
                if st.state == "unverified":
                    return False, "锁存在但无法验证进程身份（fail-safe，不抢锁）"
                if st.state == "corrupt":
                    return False, f"锁信息损坏且未过期（{st.reason}）"
                if st.state == "stale":
                    if not self._quarantine():
                        return False, "陈旧锁隔离失败"
                    continue
                return False, f"未知锁状态：{st.state}"
        return False, "获取锁失败（重试次数耗尽）"

    def _quarantine(self) -> bool:
        """把陈旧/损坏锁改名隔离，避免与其它实例竞争删除。"""
        target = f"{self.path}.stale.{uuid.uuid4().hex[:8]}"
        try:
            os.replace(self.path, target)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    # -------------------------------------------------- 释放
    def release(self) -> bool:
        if not self._held or not self.token:
            return False  # 未持有的调用方不得删除锁
        data, state = self.read()
        if data is None:
            self._held = False
            return state == "missing"
        if data.get("token") != self.token:
            return False  # 不是本实例的锁，绝不删除
        if int(data.get("pid") or 0) != os.getpid():
            return False
        try:
            os.unlink(self.path)
            self._held = False
            return True
        except OSError:
            return False

    @property
    def held(self) -> bool:
        return self._held


def _age(path: str) -> Optional[float]:
    try:
        return datetime.datetime.now().timestamp() - os.path.getmtime(path)
    except OSError:
        return None


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="HITL process lock status")
    ap.add_argument("--path", required=True)
    args = ap.parse_args(argv)
    st = ProcessLock(args.path, "probe").status()
    print(json.dumps({"state": st.state, "reason": st.reason, "info": st.info},
                     ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
