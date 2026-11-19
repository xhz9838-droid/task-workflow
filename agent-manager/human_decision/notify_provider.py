# -*- coding: utf-8 -*-
"""Notification Provider 抽象（Phase 0.5 §八）。

目标：HITL 核心（DecisionManager / ReplyHandler / 状态机）只依赖 NotificationProvider
接口与中立数据结构，不直接依赖钉钉 API；钉钉消息/回调字段转换留在 DingTalkProvider
（内部委托现有 DingTalkNotifier，不重写）。

未来 FeishuProvider / WeComProvider 实现同一接口即可替换，HITL 状态机与决策验证逻辑不变。
本模块只做接口与传输视图的定义，不改 HITL 核心逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


# ------------------------------------------------------- 中立数据结构
@dataclass(frozen=True)
class DecisionRequest:
    """决策请求的传输视图（持久模型仍是 DecisionRecord）。"""

    decision_id: str
    task_id: str
    project_key: str = ""
    level: str = ""          # P0 | P1 | P2
    question: str = ""
    options: tuple = ()
    session_ref: str = ""    # 会话引用（渠道无关；钉钉侧映射 cc_session_key）
    timeout_hint: str = ""


@dataclass(frozen=True)
class DecisionIdentity:
    """决策人身份（渠道无关）。业务授权验证用，不是宿主安全审批。"""

    user_id: str = ""
    display_name: str = ""
    channel_scope: str = ""  # private | group | cli | test | unknown
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionResponse:
    """决策回复的中立表示（入站归一化产出）。"""

    decision_id: str = ""
    option: str = ""
    free_text: str = ""
    identity: DecisionIdentity = field(default_factory=DecisionIdentity)
    msg_id: str = ""
    conversation_ref: str = ""
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderCapabilities:
    """Provider 能力声明：不支持的能力不得伪造成功，core 按此降级。"""

    inbound_callback: bool = False     # 能接收决策回复
    live_inject: bool = False          # 能向会话注入消息（恢复 Agent）
    resolve_agent_session: bool = False  # 能解析宿主 Agent 的会话 id
    transport: str = ""                # 直发 / cc-connect 等


# ------------------------------------------------------- 接口
@runtime_checkable
class NotificationProvider(Protocol):
    """通知能力接口。方法签名与现有 DingTalkNotifier 对齐（duck typing 兼容）。"""

    def capabilities(self) -> ProviderCapabilities: ...

    def send_decision_request(self, rec) -> dict:
        """发送决策请求通知。rec 为 HITL DecisionRecord。失败返回 {sent: False, ...}，不抛。"""
        ...

    def send_text(self, body: str, *, cc_project: str = "", cc_session_key: str = "") -> dict: ...

    def send_reminder(self, rec) -> dict: ...

    def send_timeout_notice(self, rec) -> dict: ...


# ------------------------------------------------------- 钉钉实现
class DingTalkProvider:
    """钉钉 Provider：包装现有 DingTalkNotifier。

    钉钉 API 地址、凭据、消息体格式、cc-connect 传输全部收敛在 DingTalkNotifier
    内部（适配层）；本类只做能力声明与接口对齐，行为不变。
    """

    def __init__(self, cfg=None, *, notifier=None, logger=None):
        if notifier is None:
            try:
                from .notifier import DingTalkNotifier
            except ImportError:
                from notifier import DingTalkNotifier  # type: ignore

            notifier = DingTalkNotifier(cfg, logger=logger)
        self._notifier = notifier

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            inbound_callback=True,   # hook 环境变量 / HTTP hook / cc-connect 会话文件
            live_inject=True,        # cc-connect /send 或 Management API
            resolve_agent_session=True,  # cc-connect agent-sid
            transport="dingtalk-direct+cc-connect",
        )

    def send_decision_request(self, rec) -> dict:
        return self._notifier.send_decision_request(rec)

    def send_text(self, body: str, *, cc_project: str = "", cc_session_key: str = "") -> dict:
        return self._notifier.send_text(body, cc_project=cc_project, cc_session_key=cc_session_key)

    def send_reminder(self, rec) -> dict:
        return self._notifier.send_reminder(rec)

    def send_timeout_notice(self, rec) -> dict:
        return self._notifier.send_timeout_notice(rec)
