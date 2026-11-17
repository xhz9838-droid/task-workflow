你是 HITL 端到端测试 Agent（第二轮）。严格按以下步骤执行：

1. 调用 MCP 工具 request_human_decision，参数：
   - task_id: "HITL-E2E-2"
   - project_key: "hitl-e2e"
   - level: "P1"
   - question: "端到端测试第二轮：请在钉钉回复 A 或 B（验证决策闭环）"
   - background: "验证修复后通道：钉钉直发通知、用户回复、阻塞恢复、按选择继续。"
   - options: [{"id":"A","description":"方案A：在结果文件中写 OK-A"},{"id":"B","description":"方案B：在结果文件中写 OK-B"}]
   - recommendation: "A"
   - recommend_reason: "测试推荐方案A"
   - risk: "不回复则任务挂起"
   - wait_seconds: 900
2. 工具返回后：
   - 若 outcome=decided 且 reply_choice 是 A 或 B：写 reports/hitl-e2e2-outcome.md，内容：
     决策编号：<decision_id>
     用户选择：<reply_choice>
     用户意见：<reply_comment 或 ->
     恢复方式：<resume_method>
     结论：OK-<reply_choice>
   - 若 outcome=decided 但回复不是 A/B（自定义意见）：写明实际回复内容，结论：CUSTOM-<内容>
   - 若 outcome=suspended：写明任务已挂起，结论：SUSPENDED
3. 结束。不要修改任何其他文件。
