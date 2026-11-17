你是 HITL 端到端测试 Agent。严格按以下步骤执行，不要做任何其他事：

1. 先把当前时间写入文件 reports/hitl-e2e-agent-before.md（内容：开始时间 + "尚未调用决策工具"）。
2. 调用 MCP 工具 request_human_decision，参数：
   - task_id: "HITL-E2E"
   - project_key: "hitl-e2e"
   - level: "P1"
   - question: "端到端测试：请选择继续方案（真实钉钉闭环验证）"
   - background: "验证 HITL 人工决策闭环：Agent 阻塞等待、钉钉通知、用户回复、恢复执行。"
   - options: [{"id":"A","description":"方案A：在 outcome 文件中写 OK-A"},{"id":"B","description":"方案B：在 outcome 文件中写 OK-B"}]
   - recommendation: "A"
   - recommend_reason: "测试推荐方案A"
   - risk: "不回复则任务挂起"
   - wait_seconds: 600
3. 工具返回后：
   - 若 outcome=decided：把用户选择写入 reports/hitl-e2e-agent-outcome.md，格式：
     决策编号：<decision_id>
     用户选择：<reply_choice>
     用户意见：<reply_comment 或 ->
     恢复方式：<resume_method>
     结论：OK-<用户选择的选项>
   - 若 outcome=suspended：写 reports/hitl-e2e-agent-outcome.md 说明任务已挂起等待决策，不要继续。
4. 结束。不要修改任何其他文件。
