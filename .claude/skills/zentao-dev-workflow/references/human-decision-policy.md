# Human Decision Policy（人工决策策略）

> 通用能力，与禅道/钉钉解耦。实现：`agent-manager/human_decision/`（MCP 工具
> `request_human_decision` / `get_human_decision` / `list_human_decisions`）。

## 何时请求人工决策

| 级别 | 场景 | 处理 |
|---|---|---|
| **P0** | 删除重要数据/文件、DDL/数据库结构变更、不可逆操作、生产环境变更、凭据/权限/安全策略变更、重大数据风险 | **必须**人工批准后才能执行 |
| **P1** | 多个合理技术方案、需求歧义、架构调整、跨模块影响、多次重试失败、业务处理方式不确定 | **建议**人工决策 |
| **P2** | 普通编码/测试/常规 Bug/依赖安装/可逆低风险操作 | Agent 自主完成，**不**触发人工 |

原则：正常任务自主完成，只有重大决策才触发人工介入；不要事事都问。

## Agent 行为规范

1. 遇到重大技术决策时主动调用 `request_human_decision` 申请确认。
2. **未获得明确批准，不得执行需要批准的操作**（P0 一律阻塞）。
3. 不得把自己的推测当作用户授权。
4. 用户明确批准后才能执行对应方案。
5. 用户要求暂停（STOP）时停止当前任务。
6. 用户提出新意见后重新评估决策（CUSTOM 意见等价方案 C）。
7. 完成后报告采用的方案和决策依据。

## 工具返回语义（关键）

`request_human_decision` 为**有界等待**（默认 300s）：

- `outcome=decided`：用户已回复。按 `decision.reply_choice` / `reply_comment` 继续执行；
  若为 `STOP`（决策状态 REJECTED），**立即停止**当前任务并报告。
- `outcome=suspended`：等待超时。**立即停止**依赖该决策的操作并结束回合（安全挂起），
  在输出中注明「任务已挂起等待决策 <decision_id>」。不得继续任何高风险操作，
  也不得自行选择方案。决策返回后由原 Session 恢复流程续跑（恢复包在
  `execution/{project}/{task}/human-decision/`）。

恢复后（收到「【人工决策已返回】」注入消息或用户回复唤醒）：

1. 调用 `get_human_decision(decision_id)` 取回已校验决策（**不要**只凭聊天原文）。
2. 不要重新开始整个任务，保留之前的执行上下文。
3. 根据用户决策调整当前实施方案，继续执行剩余步骤。
4. 完成后运行测试，最终报告任务执行结果。

## 最终报告格式（追加到执行报告）

```text
人工决策记录：

是否触发人工决策：是/否

决策编号：
DEC-3413-001

用户选择：
方案A

决策结果：
已根据用户决策继续执行。

是否完成：
是/否
```

## 恢复策略（由 Session Resumer 自动执行，Agent 无需实现）

1. **原 Session 存活**：决策直接返回给阻塞中的工具 / 经 cc-connect Management API 注入。
2. **原 Session 已退出**：cc-connect 保留 agent_session_id，用户下一条消息自动
   `--resume` 原会话；Agent 调 `get_human_decision` 取回决策。
3. **无法恢复**：按 `execution/{project}/{task}/human-decision/` 检查点包重建，
   并在报告中如实标注 resume_method=checkpoint_rebuild。
