# -*- coding: utf-8 -*-
"""P11 Agent Execution Manager — 智能任务路由 + Agent 生命周期管理 + 结果验证。

模块：
    task_router      S/M/L 智能分级 + 派发策略
    models           数据模型与状态机
    exceptions       异常体系（携带 FaultClass）
    state_manager    SQLite 状态持久化 + 任务锁 + 断点恢复
    runner           Claude Code 子进程生命周期
    monitor          进程/心跳/输出/阶段四概念监控
    retry            有限重试 + 故障分类
    verifier         结果验证质量门禁（PASS/FAIL/BLOCKED/SKIPPED/NOT_RUN）
    zentao_reporter  禅道回写（复用现有适配器）
    notifier         钉钉事件通知（复用 CC Connect）
    jenkins_adapter  Jenkins CI 接管（ai-test-* 白名单）

设计原则：
    - 复用 P01-P10 资产，不新建第二套 ZenTao/Jenkins/通知客户端
    - 简单任务 Main Agent 直通，不启动子 Agent
    - 绝不把 BLOCKED/SKIPPED/NOT_RUN 标记为 PASS
    - 不自动部署、不自动关闭禅道任务
"""
__version__ = "1.0.0"

__all__ = [
    "models",
    "exceptions",
    "task_router",
    "state_manager",
    "runner",
    "monitor",
    "retry",
    "verifier",
    "zentao_reporter",
    "notifier",
    "jenkins_adapter",
]
