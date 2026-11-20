# -*- coding: utf-8 -*-
"""HITL — Decision Detector：识别需要人工介入的场景（P0/P1/P2）。

P0 必须人工批准：删除重要数据/文件、DDL、不可逆操作、生产环境变更、
                凭据/权限/安全策略变更、重大数据风险。
P1 建议人工决策：多技术方案、需求歧义、架构变更、跨模块影响、重试仍失败、
                业务处理方式不确定。
P2 Agent 自主处理：普通编码/测试/常规 Bug/依赖安装/可逆低风险操作。

原则：正常任务 Agent 自主完成，只有重大决策才触发人工介入。
检测器只做**建议分级**；Agent 可显式指定 level（显式优先）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from human_decision.models import DecisionLevel

# 命中即升级的关键词（不区分大小写）
P0_KEYWORDS = {
    "irreversible": [
        "不可逆", "不可恢复", "永久删除", "drop table", "truncate", "delete from",
        "删库", "删除数据", "删除生产", "purge", "hard delete", "清空表",
    ],
    "ddl": [
        "ddl", "alter table", "create table", "drop index", "改表结构",
        "数据库结构变更", "修改表结构", "字段变更", "迁移数据",
    ],
    "production": [
        "生产环境", "production", "prod 发布", "生产库", "生产配置", "线上变更",
    ],
    "credentials_security": [
        "凭据", "credential", "密钥", "api key", "token 泄露", "权限变更",
        "安全策略", "鉴权策略", "证书", "password", "密码重置", "越权",
    ],
    "high_data_risk": [
        "重大数据风险", "数据丢失", "数据损坏", "批量删除", "批量更新生产",
    ],
}

P1_KEYWORDS = {
    "multi_option": ["两种方案", "多个方案", "方案 a", "方案b", "两种实现", "取舍", "权衡"],
    "ambiguity": ["需求不明确", "需求歧义", "存在歧义", "不清楚业务", "业务规则不明", "待确认"],
    "architecture": ["架构变更", "调整架构", "重构方案", "改变技术栈", "替换框架", "引入新组件"],
    "cross_module": ["影响其他模块", "跨模块", "影响范围较大", "契约变更", "breaking change"],
    "retry_failed": ["多次重试", "重试仍失败", "反复失败", "无法确定原因"],
    "business_uncertain": ["不确定业务", "业务处理方式", "无法确定正确", "需要业务确认"],
}


@dataclass
class DetectionResult:
    level: DecisionLevel
    reason: str
    matched: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"level": self.level.value, "reason": self.reason, "matched": self.matched}


def _hits(text: str, groups: dict[str, list[str]]) -> dict[str, list[str]]:
    low = text.lower()
    out = {}
    for dim, kws in groups.items():
        found = [k for k in kws if k.lower() in low]
        if found:
            out[dim] = found[:5]
    return out


def detect(
    *,
    question: str = "",
    background: str = "",
    risk: str = "",
    explicit_level: str | DecisionLevel | None = None,
) -> DetectionResult:
    """分级。显式 level 与关键词检测取**较高**等级，禁止显式降级 P0。

    兼容 L1/L2/L3（映射见 DecisionLevel.normalize）。
    """
    text = " ".join([question, background, risk])
    p0 = _hits(text, P0_KEYWORDS)
    detected: DetectionResult
    if p0:
        detected = DetectionResult(
            DecisionLevel.P0,
            "命中 P0 特征：" + "、".join(k for ks in p0.values() for k in ks[:2]),
            p0,
        )
    else:
        p1 = _hits(text, P1_KEYWORDS)
        if p1:
            detected = DetectionResult(
                DecisionLevel.P1,
                "命中 P1 特征：" + "、".join(k for ks in p1.values() for k in ks[:2]),
                p1,
            )
        else:
            detected = DetectionResult(DecisionLevel.P2, "常规任务特征，无需人工介入", {})

    if explicit_level:
        lvl = DecisionLevel.normalize(explicit_level)
        if lvl.severity < detected.level.severity:
            # 显式降级被拒绝：关键词命中更高级别时以更高级别为准
            return DetectionResult(
                detected.level,
                "显式指定 %s，但%s；按 %s 处理（禁止降级）"
                % (lvl.value, detected.reason, detected.level.value),
                detected.matched,
            )
        return DetectionResult(lvl, "Agent 显式指定 %s（检测：%s）"
                              % (lvl.value, detected.level.value))
    return detected


# --------------------------------------------------------------- 回复格式（正则）
#   <DEC-ID> A        显式决策编号 + 选项
#   A / a             选项
#   A 说明            选项 + 意见
#   C 自定义意见      未定义选项视为「自定义意见」
#   STOP / 停止 / 暂停
# 决策编号 = DEC-<task_id>-<序号>；task_id 可含多段连字符（如 HITL-A02-5A）。
# 旧式 DEC-[A-Za-z0-9]+-\w+ 会把 DEC-HITL-A02-3-13484101 截断成 DEC-HITL-A02
# （显式绑定失效，2026-11-17 验收发现），故允许 DEC- 后任意多段；
# DEC- 形状但不存在的编号仍按「未找到决策」回执（而非「无法识别」）。
DEC_ID_RE = re.compile(r"\b(DEC-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)\b", re.IGNORECASE)
STOP_WORDS = {"stop", "停止", "暂停", "终止", "abort"}
