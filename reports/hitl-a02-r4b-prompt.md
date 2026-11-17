你是 HITL 验收测试 Agent（A02-R4B：有界等待安全挂起，不自动批准，防误触重跑）。严格按以下步骤执行，不要做任何其他事：

1. 调用 MCP 工具 request_human_decision，参数：
   - task_id: "HITL-A02-4B"
   - project_key: "hitl-e2e"
   - level: "P1"
   - question: "A02-R4B 超时挂起测试：请绝对不要回复任何内容（即使误发也会被拒绝）"
   - background: "验证等待超时后安全挂起：绝不自动批准，决策保持等待状态。"
   - options: [{"id":"A","description":"方案A"},{"id":"B","description":"方案B"}]
   - recommendation: "A"
   - recommend_reason: "测试推荐方案A"
   - risk: "不回复则任务挂起"
   - wait_seconds: 90
2. 工具返回后（预期 outcome=suspended）：
   - 写 reports/hitl-a02-4b-outcome.md，结论 SUSPENDED，注明：
     - 决策编号：<decision_id>
     - outcome=<outcome>
     - 未获批准绝不放行（auto_approved 应为 False）
   - 若 outcome=decided：如实写入实际回复内容与来源，结论 REPLIED-EARLY。
3. 结束。不要修改任何其他文件，不要调用 complete。
