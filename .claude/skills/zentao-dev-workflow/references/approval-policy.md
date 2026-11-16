# 审批策略（Approval Policy）

> 对应 `CLAUDE.md` 规则 5、8。L1/L2/L3 分级。

## 分级定义

| 等级 | 典型场景 | 处理 | 是否需人工 |
|---|---|---|---|
| **L1** | 编译错误、常规 Bug、lint 警告、测试断言失败、格式问题 | Agent 自行修复 | ❌ |
| **L2** | 多个可行技术实现方案、性能取舍、重构范围、依赖版本选择、命名/结构决策 | 在**已确认设计与授权范围内**自选，记 ADR | ❌（但需记录） |
| **L3** | 业务规则不清、DDL 重大变更、API 契约破坏、生产数据风险、权限/安全风险、基础设施不可用、CI 权限/配置需管理员、跨系统重大问题 | **暂停**受影响 Agent，通知本人决策 | ✅ |

## L1：自动处理

- 重试上限：`config/workflow.yaml → retry.max_attempts`（默认 2）
- 每次重试记录原因与结果到 `run-state.retry_log[]`
- 超上限 → 节点 `BLOCKED`，升级为 L3

## L2：约束内自选 + ADR

在**已确认设计和授权范围内**自主决策：

- 生成 ADR（Architecture Decision Record）到 `execution/{project}/{task}/decisions.md`
- ADR 必须含：背景、可选方案、决策、理由、影响范围、是否可逆
- **不**突破已确认的需求和设计
- **不**修改公共接口/业务规则（那是 L3）

## L3：暂停 + 人工决策

### 必须走 L3 的场景

1. 业务规则不清晰 / 需求歧义
2. DDL 重大变更（删列、改语义、大表重构）
3. API 契约破坏（改签名、删字段、改语义）
4. 生产数据风险
5. 权限或安全风险（越权、数据泄露、凭据问题）
6. 无法访问公司基础设施（CI、任务系统、内部服务）
7. CI 权限或配置需管理员介入
8. 跨系统重大问题
9. 需要部署 / 重启服务 / 修改全局配置
10. 超过重试上限的阻塞

### L3 处理流程

```text
① 暂停受影响 Agent（其他独立节点继续推进）
② 创建 L3 记录（blockers[] 含 id/level/summary/wait_for/resume_steps）
③ 保存上下文：Session ID、Workflow/Task ID、Git 分支、Worktree、当前阶段
④ 经通知渠道发送（scripts/notify.sh）
   消息必含：project_key、task_id、SessionID、BlockerID、阶段、
            问题描述、影响范围、推荐方案、等待决策项
⑤ 等待本人决策（不挂起进程数日）
⑥ 收到决策 → 记录到 decisions.md + run-state.blockers[].resolution
⑦ 同步受影响 Agent
⑧ 恢复执行（可经 Session Resume 或 Dispatcher）
```

### L3 消息模板

```text
【AI 研发工作流 · 人工决策】
project_key: {project_key}
task_id: {task_id}
Session ID: {session_id}
Blocker ID: {blocker_id}
阶段: {stage}

问题: {summary}
影响范围: {impact}
推荐方案: {recommendation}

需要您决策：
{questions}

回复后自动恢复执行。
```

## 审批边界（不需人工，但需记录）

| 操作 | 是否需人工 | 说明 |
|---|---|---|
| 修改业务代码 | ❌（设计已确认） | worktree 内 |
| 编写测试 | ❌ | |
| 运行 lint/build | ❌ | |
| 触发白名单 CI Job | ❌ | 仅测试 Job |
| 进度回写（追加） | ❌ | 适配器 + 读回核验 |
| **设计确认** | ✅ | 未确认不进编码 |
| **部署/重启** | ✅ | 严禁自动 |
| **关闭业务任务** | ✅ | 严禁自动 |
| **修改全局配置** | ✅ | |
| **改他人任务** | ✅ | 严禁 |
| **DDL 破坏性变更** | ✅ | |
| **API 契约变更** | ✅ | |

## 审计

所有 L2/L3 决策写入：
- `execution/{project}/{task}/decisions.md`（人读）
- `execution/{project}/{task}/audit.jsonl`（机读，`scripts/audit.py`）

禁止写入：凭据、token、完整连接串、私钥。
