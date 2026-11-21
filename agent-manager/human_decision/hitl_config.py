# -*- coding: utf-8 -*-
"""HITL — 配置加载。

来源（后者覆盖前者）：
    内置默认 → config/adapters/hitl.yaml（存在则读）→ 环境变量覆盖敏感项

敏感信息：
    - cc-connect management token：优先 ${CC_MGMT_TOKEN}，否则从
      ~/.cc-connect/config.toml 的 [management] token 读取（只读，不打印、不落盘）。
    - 钉钉授权决策人白名单：config/adapters/hitl.yaml（user_id 非机密）。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))  # task-workflow/
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

DEFAULTS = {
    "enabled": True,
    "deciders": [],                     # [{"user_id": "...", "name": "..."}]
    "any_private_chat_user": False,     # fail-closed：须显式配置决策人；True 才放行单聊会话主人
    "tool_wait_seconds": 300,           # MCP 工具有界等待
    "poll_interval_seconds": 2,
    "remind_after_seconds": 1800,
    "timeout_after_seconds": 86400,
    "notify_retries": 3,
    "notify_retry_interval_seconds": 5,
    "notify_transport": ["dingtalk_direct", "cc_connect"],
    "dingtalk_user_id": "",
    "cc_connect_bin": "cc-connect",
    "cc_data_dir": "",                  # 空 = ~/.cc-connect
    "management_api": "http://127.0.0.1:9820",
    "management_token": "",
    "watch_session_files": True,
    "hook_endpoint_host": "127.0.0.1",
    "hook_endpoint_port": 9411,
    "resume_order": ["live_continue", "cc_connect_resume", "checkpoint_rebuild"],
    "dry_run_notify": False,
}


@dataclass
class HitlConfig:
    enabled: bool = True
    deciders: list[dict] = field(default_factory=list)
    any_private_chat_user: bool = False
    tool_wait_seconds: int = 300
    poll_interval_seconds: float = 2.0
    remind_after_seconds: int = 1800
    timeout_after_seconds: int = 86400
    notify_retries: int = 3
    notify_retry_interval_seconds: int = 5
    notify_transport: list[str] = field(default_factory=lambda: ["dingtalk_direct", "cc_connect"])
    dingtalk_user_id: str = ""  # 直发通道目标用户；空 = 从 cc_session_key 单聊键尾段解析
    cc_connect_bin: str = "cc-connect"
    cc_data_dir: str = ""
    management_api: str = "http://127.0.0.1:9820"
    management_token: str = ""
    watch_session_files: bool = True
    hook_endpoint_host: str = "127.0.0.1"
    hook_endpoint_port: int = 9411
    resume_order: list[str] = field(default_factory=lambda: ["live_continue", "cc_connect_resume", "checkpoint_rebuild"])
    dry_run_notify: bool = False
    execution_root: str = ""  # 空 = <repo>/execution（检查点包根目录）

    def sessions_dir(self) -> str:
        if self.cc_data_dir:
            return os.path.join(self.cc_data_dir, "sessions")
        env = os.environ.get("CC_CONNECT_DATA_DIR") or os.environ.get("CC_DATA_DIR")
        base = env or os.path.join(os.path.expanduser("~"), ".cc-connect")
        return os.path.join(base, "sessions")

    def discover_chat_binding(self) -> tuple[str, str]:
        """无 CC_PROJECT/CC_SESSION_KEY 时，从 cc-connect 会话文件推断私聊绑定。

        返回 (project, session_key)。只读；优先匹配配置的 dingtalk_user_id，
        否则取最近更新的单聊会话。无法确定 → ("", "")（不猜测）。
        """
        import glob
        import json

        sdir = self.sessions_dir()
        if not os.path.isdir(sdir):
            return "", ""
        uid = (self.dingtalk_user_id or "").strip()
        if not uid:
            ids = sorted(self.decider_ids())
            if len(ids) == 1:
                uid = ids[0]
        if not uid:
            return "", ""  # 无明确用户 → 不猜测聊天绑定
        cands = []
        for path in glob.glob(os.path.join(sdir, "*.json")):
            try:
                mtime = os.path.getmtime(path)
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            project = os.path.basename(path).split("_", 1)[0]
            keys = []
            for field in ("active_session", "user_meta"):
                block = data.get(field) or {}
                if isinstance(block, dict):
                    keys.extend(block.keys())
            for key in keys:
                key = str(key)
                if not key.startswith("dingtalk:d:"):
                    continue
                if uid and not key.endswith(":" + uid):
                    continue
                cands.append((mtime, project, key))
        if not cands:
            return "", ""
        cands.sort(reverse=True)
        return cands[0][1], cands[0][2]

    def project_for_session_key(self, session_key: str) -> str:
        """dingtalk 会话键 → cc-connect 项目名（会话文件名前缀）。无法确定 → ""。"""
        import glob
        import json

        if not session_key:
            return ""
        raw = (session_key or "").strip()
        if raw.startswith("dingtalk:") and raw.count(":") >= 3:
            raw = raw[len("dingtalk:"):]
        sdir = self.sessions_dir()
        for path in glob.glob(os.path.join(sdir, "*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            keys = set()
            for field in ("active_session", "user_meta"):
                block = data.get(field) or {}
                if isinstance(block, dict):
                    keys.update(str(k) for k in block.keys())
            if session_key in keys:
                return os.path.basename(path).split("_", 1)[0]
        return ""

    def decider_ids(self) -> set[str]:
        return {str(d.get("user_id", "")) for d in self.deciders if d.get("user_id")}

    def is_authorized(self, user_id: str | None, *, chat_scope: str = "") -> bool:
        """是否授权决策人（fail-closed）。

        - 白名单命中 → True
        - 白名单为空且 any_private_chat_user=True 且单聊 → 会话主人（best-effort）
        - **其余一律 False**（默认不放行任何用户）
        """
        if user_id and user_id in self.decider_ids():
            return True
        if not self.deciders and self.any_private_chat_user:
            if str(chat_scope).startswith("d") or chat_scope == "private":
                return True
        return False

    def config_error(self) -> str:
        """未配置决策人时的明确错误提示（不静默使用开发者身份）。"""
        if self.deciders:
            return ""
        if self.any_private_chat_user:
            return ""
        return (
            "HITL 未配置授权决策人。请在 config/adapters/hitl.local.yaml 配置 deciders，"
            "或设环境变量 HITL_DECIDER_IDS=<userId1,userId2>，"
            "或临时置 any_private_chat_user: true（仅单聊会话主人，不推荐）。"
        )


def resolve_cc_connect_bin(name: str = "cc-connect") -> str:
    """解析 cc-connect 可执行文件。

    Windows 下 Python subprocess 不能像 shell 一样解析 npm 全局的 sh/cmd 包装，
    这里显式用 shutil.which（含 PATHEXT）+ 常见 npm 全局路径兜底。
    """
    import shutil

    if os.path.dirname(name):
        return name
    for cand in (name, name + ".cmd", name + ".exe"):
        found = shutil.which(cand)
        if found:
            return found
    for cand in (
        os.path.expanduser("~/npm-global/cc-connect.cmd"),
        os.path.expanduser("~/npm-global/cc-connect"),
        os.path.expanduser("~/AppData/Roaming/npm/cc-connect.cmd"),
        os.path.expanduser("~/.npm-global/bin/cc-connect"),
    ):
        if os.path.exists(cand):
            return cand
    return name  # 交由调用方报错（明确失败优于猜测）


def _read_yaml(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    if path.endswith(".json"):
        import json

        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _read_mgmt_token_from_cc_config() -> str:
    """从 cc-connect config.toml 读取 [management] token（只读，不外泄）。"""
    for base in (
        os.environ.get("CC_CONNECT_DATA_DIR") or os.environ.get("CC_DATA_DIR"),
        os.path.join(os.path.expanduser("~"), ".cc-connect"),
    ):
        if not base:
            continue
        for name in ("config.toml", os.path.join("config", "config.toml")):
            path = os.path.join(base, name)
            if not os.path.exists(path):
                continue
            try:
                import tomllib

                with open(path, "rb") as f:
                    data = tomllib.load(f)
                tok = ((data.get("management") or {}).get("token")) or ""
                if tok:
                    return str(tok)
            except Exception:
                continue
    return ""


def load_config(path: str | None = None) -> HitlConfig:
    """加载 HITL 配置（分层，后者覆盖前者）：

    1. 内置默认 DEFAULTS
    2. config/adapters/hitl.yaml          通用配置（Git 提交）
    3. config/adapters/hitl.local.yaml    个人本地配置（gitignored，含 userId）
    4. 环境变量                            HITL_DECIDER_IDS / HITL_DINGTALK_USER_ID 等

    个人身份与凭据**不写入 Git**。
    """
    cfg_path = path or os.path.join(_ROOT, "config", "adapters", "hitl.yaml")
    raw = dict(DEFAULTS)

    # 1) 通用配置
    for k, v in (_read_yaml(cfg_path).get("human_decision") or {}).items():
        if k in raw:
            raw[k] = v

    # 2) 个人本地配置（gitignored）—— 同目录 hitl.local.yaml
    if path is None:
        local_path = os.path.join(_ROOT, "config", "adapters", "hitl.local.yaml")
        if os.path.exists(local_path):
            for k, v in (_read_yaml(local_path).get("human_decision") or {}).items():
                if k in raw:
                    raw[k] = v

    # 3) 环境变量覆盖（个人身份 + 敏感凭据）
    env_deciders = os.environ.get("HITL_DECIDER_IDS", "").strip()
    if env_deciders:
        raw["deciders"] = [
            {"user_id": u.strip(), "name": u.strip()}
            for u in env_deciders.split(",") if u.strip()
        ]
    if os.environ.get("HITL_DINGTALK_USER_ID"):
        raw["dingtalk_user_id"] = os.environ["HITL_DINGTALK_USER_ID"]
    if os.environ.get("HITL_ANY_PRIVATE_CHAT_USER", "").lower() in ("1", "true", "yes"):
        raw["any_private_chat_user"] = True
    elif os.environ.get("HITL_ANY_PRIVATE_CHAT_USER", "").lower() in ("0", "false", "no"):
        raw["any_private_chat_user"] = False

    if os.environ.get("CC_MGMT_TOKEN"):
        raw["management_token"] = os.environ["CC_MGMT_TOKEN"]
    if not raw.get("management_token"):
        raw["management_token"] = _read_mgmt_token_from_cc_config()

    known = set(DEFAULTS)
    return HitlConfig(**{k: v for k, v in raw.items() if k in known})
