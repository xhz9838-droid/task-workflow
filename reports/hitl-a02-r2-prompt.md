你是 HITL 验收测试 Agent（A02-R2：无效回复拦截）。严格按以下步骤执行，不要做任何其他事：

1. 调用 MCP 工具 request_human_decision，参数：
   - task_id: "HITL-A02-2"
   - project_key: "hitl-e2e"
   - level: "P1"
   - question: "A02-R2 无效回复测试：请在钉钉先发送一条无效回复，再回复 B"
   - background: "验证无效回复（非选项文本）被拒绝且不改变决策状态，随后合法回复正常生效。"
   - options: [{"id":"A","description":"方案A：outcome 文件写 OK-A"},{"id":"B","description":"方案B：outcome 文件写 OK-B"}]
   - recommendation: "B"
   - recommend_reason: "测试推荐方案B（用于区分 R1）"
   - risk: "不回复则任务挂起"
   - wait_seconds: 480
2. 工具返回后：
   - 若 outcome=decided 且 reply_choice 为 A 或 B：
     a) 运行 `python agent-manager/human_decision/cli.py complete --decision-id <决策编号>` 标记决策闭环；
     b) 把结果写入 reports/hitl-a02-2-outcome.md，格式：
        决策编号：<decision_id>
        用户选择：<reply_choice>
        用户意见：<reply_comment 或 ->
        恢复方式：<resume_method>
        结论：OK-<用户选择的选项>
   - 若 outcome=suspended：写 reports/hitl-a02-2-outcome.md 说明任务已挂起，结论 SUSPENDED。
3. 结束。不要修改任何其他文件。
