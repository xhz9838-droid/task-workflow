# -*- coding: utf-8 -*-
"""P11 Agent Execution Manager — 异常体系。

异常携带 FaultClass，决定 retry 策略：
    TRANSIENT -> 可自动重试
    PERMANENT -> 交回 Main Agent 分析，不盲目重启
    HUMAN     -> 停止并请求人工
"""
from __future__ import annotations

import os as _os
import sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
if _here not in _sys.path:
    _sys.path.insert(0, _here)

try:
    from .models import FaultClass
except ImportError:  # 直接脚本运行
    from models import FaultClass  # type: ignore


class AgentManagerError(Exception):
    """基类"""

    fault: FaultClass = FaultClass.PERMANENT

    def __init__(self, message: str, *, fault: FaultClass | None = None):
        super().__init__(message)
        if fault is not None:
            self.fault = fault


class ConfigError(AgentManagerError):
    """配置缺失或非法 —— 不猜测，明确报错"""

    fault = FaultClass.PERMANENT


class TaskLockError(AgentManagerError):
    """同一 task_id 已有运行实例"""

    fault = FaultClass.HUMAN


class DuplicateExecutionError(AgentManagerError):
    """重复领取/重复启动 —— 禁止"""

    fault = FaultClass.HUMAN


class AgentStartError(AgentManagerError):
    """进程启动失败 —— 可能瞬时（资源）或永久（CLI 不存在）"""

    fault = FaultClass.TRANSIENT


class AgentTimeoutError(AgentManagerError):
    """阶段超时"""

    fault = FaultClass.PERMANENT


class AgentCrashError(AgentManagerError):
    """异常退出（非零退出码 / 信号）"""

    fault = FaultClass.PERMANENT


class TransientError(AgentManagerError):
    """网络/服务瞬时故障 —— 可重试"""

    fault = FaultClass.TRANSIENT


class CodeError(AgentManagerError):
    """代码逻辑错误 / 测试失败 / lint 错误 —— 不盲目重试，交回 Main Agent"""

    fault = FaultClass.PERMANENT


class VerificationError(AgentManagerError):
    """验证失败 —— 质量门禁拒绝"""

    fault = FaultClass.PERMANENT


class BlockedError(AgentManagerError):
    """环境/权限阻塞 —— 需人工或环境就绪"""

    fault = FaultClass.HUMAN


class ZenTaoWriteError(AgentManagerError):
    """禅道回写失败 —— 事件须持久化待重试，不丢执行结果"""

    fault = FaultClass.TRANSIENT


class NotifyError(AgentManagerError):
    """通知失败 —— 记录但不导致开发任务失败"""

    fault = FaultClass.TRANSIENT


class JenkinsUnavailableError(AgentManagerError):
    """Jenkins 不可用 —— 记 BLOCKED，不伪装通过"""

    fault = FaultClass.HUMAN
