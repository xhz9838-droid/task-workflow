# -*- coding: utf-8 -*-
"""P11 Phase 1 — 智能任务路由 Task Router。

S/M/L 分级（P11 §三）：
    S 简单  : Main Agent 直通，0 子 Agent
    M 中等  : 按需选择性子 Agent
    L 大型  : 完整多 Agent 工作流

分级**不只看文件数**，综合：文件数量、业务复杂度、跨仓库、数据库变更、
API 契约变化、安全风险、回滚难度、测试环境要求。

高风险情况即使单文件也**不归 S**。

用户指令优先（P11 §三.4）：用户明确说"不用子 Agent/跳过 Build/只做静态检查"
时，必须覆盖默认工作流。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:  # 作为包导入
    from .models import RouteDecision, TaskLevel, WorkflowType
    from .exceptions import ConfigError
except ImportError:  # 直接脚本运行
    from models import RouteDecision, TaskLevel, WorkflowType  # type: ignore
    from exceptions import ConfigError  # type: ignore


# --------------------------------------------------------------- 风险信号
# 关键词命中即视为对应风险维度（用于分类理由与风险计分）
RISK_KEYWORDS = {
    "db_change": [
        "ddl", "migration", "migrate", "建表", "改表", "加字段", "删字段", "索引",
        "数据库", "database", "schema", "实体", "entity", "mybatis", "mapper.xml",
    ],
    "api_contract": [
        "openapi", "接口", "api", "契约", "controller", "endpoint", "签名",
        "对外", "third-party", "第三方",
    ],
    "security": [
        "权限", "permission", "auth", "认证", "鉴权", "越权", "security",
        "加密", "encrypt", "token", "密码", "password", "secret", "支付", "pay",
    ],
    "cross_repo": [
        "跨仓库", "cross-repo", "前后端", "联调", "三端", "web + mobile",
        "backend + frontend", "多仓库",
    ],
    "business_logic": [
        "业务流程", "状态机", "审批", "workflow", "状态流转", "事务",
        "transaction", "计算", "统计", "核算", "薪酬", "工资",
    ],
    "rollback_risk": [
        "生产", "production", "发布", "release", "部署", "deploy",
        "数据迁移", "不可逆", "irreversible",
    ],
    "simple_change": [
        "文案", "文本", "css", "样式", "style", "颜色", "color", "间距",
        "spacing", "配置", "config", "注释", "comment", "readme", "文档",
        "typo", "改名", "rename", "ui 调整", "按钮",
    ],
}


@dataclass
class TaskSignal:
    """分类输入信号（P11 §三.2：综合多维度，不只看文件数）"""

    file_count: int = 0
    file_paths: list[str] = field(default_factory=list)
    description: str = ""
    affected_repos: list[str] = field(default_factory=list)
    touches_db: bool = False
    touches_api: bool = False
    touches_security: bool = False
    cross_repo: bool = False
    high_risk: bool = False
    needs_test_env: bool = False
    business_complexity: str = "low"  # low | medium | high
    # 用户显式指令（最高优先级）
    user_no_subagents: bool = False
    user_skip_build: bool = False
    user_static_only: bool = False
    user_quick_verify: bool = False

    def matched_keywords(self, dim: str) -> list[str]:
        text = (self.description + " " + " ".join(self.file_paths)).lower()
        return [k for k in RISK_KEYWORDS.get(dim, []) if k in text]


# --------------------------------------------------------------- 分类器
class TaskRouter:
    """S/M/L 分级 + 派发策略。"""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        routing = self.config.get("routing", {}) or {}
        self.simple_subagents = bool(routing.get("simple", {}).get("subagents", False))
        self.default_budget = int(
            (self.config.get("execution", {}) or {}).get("default_budget_seconds", 1800)
        )

    # ---------- 主入口 ----------
    def classify(self, task_id: str, project_key: str, signal: TaskSignal) -> RouteDecision:
        level, reason, risk_hits = self._score(signal)
        workflow = {
            TaskLevel.S: WorkflowType.DIRECT,
            TaskLevel.M: WorkflowType.SELECTIVE,
            TaskLevel.L: WorkflowType.FULL,
        }[level]

        agents = self._select_agents(level, signal)
        tests = self._select_tests(level, signal)
        budget = self._budget(level)

        overrides = {
            k: v
            for k, v in {
                "user_no_subagents": signal.user_no_subagents,
                "user_skip_build": signal.user_skip_build,
                "user_static_only": signal.user_static_only,
                "user_quick_verify": signal.user_quick_verify,
            }.items()
            if v
        }

        # 用户指令优先（P11 §三.4）
        if signal.user_no_subagents:
            agents = []
            workflow = WorkflowType.DIRECT
        if signal.user_static_only or signal.user_quick_verify:
            tests = [t for t in tests if t in ("static", "lint")]
        if signal.user_skip_build:
            tests = [t for t in tests if t != "build"]

        return RouteDecision(
            task_id=str(task_id),
            project_key=project_key,
            task_level=level,
            classification_reason=reason,
            selected_workflow=workflow,
            selected_agents=agents,
            expected_tests=tests,
            execution_budget_seconds=budget,
            user_overrides=overrides,
        )

    # ---------- 打分 ----------
    def _score(self, s: TaskSignal) -> tuple[TaskLevel, str, dict]:
        reasons: list[str] = []
        risk_hits: dict = {}

        # 硬性升级条件（高风险即使单文件也不归 S）
        hard = []
        if s.touches_db:
            hard.append("数据库变更")
        if s.touches_api:
            hard.append("API 契约变化")
        if s.touches_security:
            hard.append("安全/权限逻辑")
        if s.cross_repo or len(s.affected_repos) > 1:
            hard.append("跨仓库修改")
        if s.high_risk:
            hard.append("高风险（回滚难/生产影响）")
        if s.business_complexity == "high":
            hard.append("复杂业务逻辑")

        for dim in ("db_change", "api_contract", "security", "cross_repo", "rollback_risk", "business_logic"):
            hits = s.matched_keywords(dim)
            if hits:
                risk_hits[dim] = hits[:5]

        if hard:
            reasons.append("硬性升级维度：" + "、".join(hard))
            level = TaskLevel.L if (
                len(hard) >= 2
                or s.cross_repo
                or s.business_complexity == "high"
                or s.touches_db and s.touches_api
            ) else TaskLevel.M
            # 跨仓库 / 高复杂度 / 多风险 → L
            return level, "；".join(reasons), risk_hits

        # 无硬性风险 → 按规模与复杂度
        if s.business_complexity == "medium":
            reasons.append("业务复杂度 medium")
            return TaskLevel.M, "；".join(reasons), risk_hits

        if s.file_count <= 3 and s.business_complexity == "low":
            simple_hits = s.matched_keywords("simple_change")
            if simple_hits or s.file_count <= 1:
                reasons.append(f"小范围修改（{s.file_count} 文件）")
                if simple_hits:
                    reasons.append("命中简单变更特征：" + "、".join(simple_hits[:3]))
                reasons.append("无数据库/API/安全/跨仓库风险")
                return TaskLevel.S, "；".join(reasons), risk_hits

        if s.file_count <= 12:
            reasons.append(f"中等规模（{s.file_count} 文件）")
            return TaskLevel.M, "；".join(reasons), risk_hits

        reasons.append(f"大规模（{s.file_count} 文件）")
        return TaskLevel.L, "；".join(reasons), risk_hits

    # ---------- 派发 ----------
    def _select_agents(self, level: TaskLevel, s: TaskSignal) -> list[str]:
        """S: 0 个；M: 按需；L: 完整。"""
        if level == TaskLevel.S:
            return [] if not self.simple_subagents else ["dw-qa-engineer"]

        if level == TaskLevel.M:
            agents = ["dw-web-frontend"] if any("vue" in p or "web" in p or "ui" in p for p in s.file_paths) else []
            if s.touches_db:
                agents.append("dw-database")
            if any("java" in p or "backend" in p or "biz" in p for p in s.file_paths):
                agents.append("dw-java-backend")
            agents.append("dw-qa-engineer")  # M：定向 QA
            return sorted(set(agents))

        # L：完整工作流
        base = ["dw-architect", "dw-qa-engineer", "dw-integration-reviewer"]
        if s.touches_db:
            base.append("dw-database")
        if any("java" in p or "backend" in p for p in s.file_paths) or s.affected_repos:
            base.append("dw-java-backend")
        if any("vue" in p or "web" in p or "ui" in p for p in s.file_paths):
            base.append("dw-web-frontend")
        if any("app" in p or "mobile" in p or "uniapp" in p for p in s.file_paths):
            base.append("dw-mobile-app")
        return sorted(set(base))

    def _select_tests(self, level: TaskLevel, s: TaskSignal) -> list[str]:
        """不为每个任务默认跑全部测试（P11 §五.1）。"""
        if level == TaskLevel.S:
            t = ["static", "lint"]
            if not s.user_static_only:
                t.append("build")
            return t
        if level == TaskLevel.M:
            return ["static", "lint", "unit", "build"]
        t = ["static", "lint", "unit", "build"]
        if s.touches_api:
            t.append("api")
        if s.needs_test_env:
            t.append("e2e")
        return t

    def _budget(self, level: TaskLevel) -> int:
        return {
            TaskLevel.S: 600,
            TaskLevel.M: self.default_budget,
            TaskLevel.L: self.default_budget * 2,
        }[level]


# --------------------------------------------------------------- 便捷入口
def route(task_id: str, project_key: str, signal: TaskSignal, config: dict | None = None) -> RouteDecision:
    return TaskRouter(config).classify(task_id, project_key, signal)
