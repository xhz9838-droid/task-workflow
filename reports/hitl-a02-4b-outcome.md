# HITL A02-R4B 超时挂起测试 — 结果报告

- 测试用例：A02-R4B（有界等待安全挂起，不自动批准，防误触重跑）
- task_id: HITL-A02-4B
- project_key: hitl-e2e
- level: P1
- 执行时间：2026-11-17

## 结论：REPLIED-EARLY

预期 outcome=suspended（等待 90 秒超时后安全挂起），实际 outcome=decided。
在有界等待窗口内收到真人回复，决策被提前裁决，**未走到超时挂起路径**。

## 关键事实

- 决策编号：DEC-HITL-A02-4B-14012301
- outcome=decided（预期为 suspended）
- 决策状态：RESUMED
- auto_approved 应为 False — 实际未发生自动批准：裁决来自真人回复，非自动放行；未获批准绝不放行的约束未被触发（因为存在有效人工回复）

## 实际回复内容与来源

- user_reply: "A"
- reply_kind: option
- reply_choice: A
- reply_comment: （无）
- 回复来源：钉钉（cc_session_key: dingtalk:d:cidSMSg0KkgNzAaeL1GcWcR8dGpepImrpvAWt9tJA3q9CU=:17248148409976157）
- 回复人：徐弘祖（user_id: 17248148409976157）

## 时间线

| 事件 | 时间（+08:00） |
|---|---|
| created_at | 2026-11-17T14:01:23 |
| notified_at | 2026-11-17T14:01:24 |
| replied_at | 2026-11-17T14:01:35 |
| resumed_at | 2026-11-17T14:01:35 |
| resume_method | live_continue |

从通知到回复约 11 秒，远早于 wait_seconds=90 的超时窗口。

## 判定说明

- 本次运行**未能验证**"等待超时后安全挂起"行为，因为回复在超时前到达。
- 未观察到自动批准：决策由人工回复 "A" 驱动（recommended_option 为 A，但裁决依据是 user_reply=A 的真人输入）。
- 如需验证 suspended 路径，需重跑 A02-R4B 且在整个 wait_seconds 窗口内确保无人回复（含误发）。

## 防误触重跑说明

本次为唯一一次 request_human_decision 调用，未重跑、未重复创建决策。
