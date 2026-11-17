你是 HITL 验收测试 Agent（A02-R3：未授权用户拒绝，fail-closed）。严格按以下步骤执行，不要做任何其他事：

1. 调用 MCP 工具 request_human_decision，参数：
   - task_id: "HITL-A02-3"
   - project_key: "hitl-e2e"
   - level: "P1"
   - question: "A02-R3 未授权测试：请在钉钉回复 A（本决策的授权白名单不包含你，预期被拒绝）"
   - background: "验证 fail-closed 身份校验：白名单外用户回复被拒绝、决策不被采纳、不自动放行。"
   - options: [{"id":"A","description":"方案A"},{"id":"B","description":"方案B"}]
   - recommendation: "A"
   - recommend_reason: "测试推荐方案A"
   - risk: "不回复则任务挂起"
   - wait_seconds: 150
2. 工具返回后，如实记录到 reports/hitl-a02-3-outcome.md：
   - 若 outcome=suspended（预期）：结论 SUSPENDED，说明未授权回复已被拒绝、决策未放行。
   - 若 outcome=decided：结论 ACCEPTED-BY-GLOBAL-CONFIG，注明实际回复内容与处理路径（可能被全局放行配置的 daemon 进程接受——白名单为处理进程级配置，非决策级）。
3. 结束。不要修改任何其他文件，不要调用 complete。
