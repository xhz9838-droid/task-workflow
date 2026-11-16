# 中断恢复协议（Recovery Protocol）

> 对应 `CLAUDE.md` 规则 6、7。

## 恢复触发条件

- 会话中断后重启
- `/zentao-dev-workflow {project_key} {task_id}` 且 `execution/{project}/{task}/` 已存在
- Agent 超时/卡住需接管
- 阻塞解除后继续

## 恢复步骤（必做，顺序执行）

```text
① 读取项目配置   config/projects/{project_key}.yaml
② 读取任务状态   execution/{project}/{task}/run-state.json + tasks.yaml
③ 读取最近报告   agent-reports/*.json（按时间排序）
④ 检查 Git/Worktree
   - 每个已登记 worktree 的分支、HEAD commit、脏文件
   - 与 run-state.worktrees[] 对比，识别漂移
⑤ 节点分类：done / failed / blocked / pending / unverified
⑥ 从最近可信检查点继续
```

## 可信检查点

`run-state.json → checkpoints[]`，每项记录：

```json
{
  "at": "ISO8601",
  "stage": "T06-W1",
  "completed_nodes": ["W1"],
  "next_nodes": ["QA1"],
  "evidence": {"W1": {"commit": "…", "report": "…"}}
}
```

**规则**：取最后一个 `completed_nodes` 与实际 Git 状态**一致**的检查点；不一致则以实际 Git 状态为准修正 DAG。

## 禁止重复已完成节点

已完成 = 报告存在 + 证据齐全 + Git 核验通过（见 continuation-protocol 规则 4）。

**不得**仅因状态文件陈旧就重跑已验证节点。

## 节点状态判定

| 状态 | 判定 |
|---|---|
| `done` | 报告 + 证据 + Git 核验全通过 |
| `unverified` | 报告声明 done 但证据不全 → 要求补证据，**不重跑** |
| `failed` | 报告 status=failed，或测试失败 |
| `blocked` | L3 阻塞，或依赖缺失 |
| `pending` | 未执行 |

## Worktree 漂移处理

| 情况 | 处理 |
|---|---|
| worktree 存在且 commit 匹配 | 正常恢复 |
| worktree 有未提交改动 | 保留，不 reset；询问是否继续 |
| worktree 分支丢失 | 从 `run-state` 记录的 commit 重建 |
| 主工作区有未提交改动 | **不动**，继续用 worktree |
| run-state 记录的 commit 不存在 | 标 `unverified`，人工确认 |

## 重试策略

| 项 | 值（可配） |
|---|---|
| 默认最大重试 | `config/workflow.yaml → retry.max_attempts`（默认 2） |
| 策略 | `retry.strategy`（默认 exponential-backoff） |
| 每次重试 | 记录 `reason` + `attempt` + `result` 到 `run-state.retry_log[]` |
| 超上限 | 节点标记 `BLOCKED` |
| L3 | **必须**人工确认，不自动重试 |

## 中断时的未完成工作

- 未完成节点保留在 `tasks.yaml`（状态 `pending`）
- 未完成 Agent 报告标 `incomplete`
- 未完成的 CI 构建：记录 Build Number，恢复时查询最终结果（不重新触发，除非结果为 NOT_BUILT）
- 未完成的 L3 阻塞：保留，恢复时重新发起通知

## 恢复验证

恢复后必须输出：

1. 已完成节点清单（含证据引用）
2. 待执行节点清单（含依赖关系）
3. 阻塞节点清单（含原因与恢复条件）
4. 本轮将执行的节点
