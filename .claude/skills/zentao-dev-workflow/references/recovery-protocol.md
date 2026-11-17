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

`run-state.json → checkpoints[]`（由 `dispatch.py export-state` 从 SQLite 导出），每项记录：

```json
{
  "at": "ISO8601",
  "stage": "T06-W1",
  "completed_nodes": ["W1"],
  "next_nodes": ["QA1"],
  "evidence": {"W1": {"commit": "…", "report": "…"}}
}
```

**规则**：取最后一个 `completed_nodes` 与 SQLite `node_dispatches`（DONE 节点）**一致**的检查点；不一致则以 SQLite 为准修正 DAG。`run-state.json` 是只读快照，**真相在 SQLite**。

## 禁止重复已完成节点

已完成 = 报告存在 + 证据齐全 + Git 核验通过（见 continuation-protocol 规则 4）。

**不得**仅因状态文件陈旧就重跑已验证节点。

## 节点状态判定

> **状态唯一真相源 = agent-manager SQLite（`node_dispatches` 表）**。`run-state.json` 仅作 `dispatch.py export-state` 导出的只读快照，不得直接修改。恢复时**先核对 SQLite 执行凭证**，再决定是否重派。

### NodeState 状态机

```
PENDING → DISPATCHING → RUNNING → DONE
DISPATCHING → FAILED | UNVERIFIED（待对账）
RUNNING → FAILED | BLOCKED | UNVERIFIED
FAILED → RETRY_PENDING → DISPATCHING（新 attempt）
BLOCKED → DISPATCHING（阻塞解除后重派）
```

| 状态 | 判定 | 恢复动作 |
|---|---|---|
| `done` | SQLite node_dispatches.status=DONE + 报告 + 证据 + Git 核验全通过 | 不重跑 |
| `dispatching` | 已登记 attempt_id，主控未取得 agent_id（未真正派发） | 检查是否真派发；DISPATCHING 超时（>600s 无 confirm）→ reconcile 标 UNVERIFIED |
| `running` | agent_id 已确认（CLAUDE_TOOL）/ pid 已确认（CLI） | 见下方"僵尸 RUNNING 检测" |
| `unverified` | 对账无法确认真实状态（无凭证 / CLAUDE_TOOL 无 pid 探活 / 历史无凭证 running 迁移） | **不假定成功/失败**，人工确认后重派新 attempt |
| `failed` | 报告 status=failed / 测试失败 / 进程死（CLI） | 按重试策略：TRANSIENT→新 attempt，PERMANENT→交主控 |
| `blocked` | L3 阻塞 / 依赖缺失 | 不自动推进；阻塞解除后重派新 attempt |
| `pending` | 未派发 | 进入 plan 可执行列表 |

### 执行后端区分（不得伪造）

| 后端 | 凭证 | 探活能力 |
|---|---|---|
| `claude_tool`（Claude Code Agent Tool） | `agent_id`（字符串），无 pid | **无进程探活**；RUNNING 只能靠 task-notification 或报告落盘确认，否则 reconcile 标 UNVERIFIED |
| `cli_subprocess`（Claude CLI 子进程） | `pid` | `pid_alive` 可探活；pid 死 → FAILED |

**禁止**：对 CLAUDE_TOOL backend 伪造 pid；对任一 backend 在无凭证时标 RUNNING。

### 僵尸 RUNNING 检测（reconcile）

恢复时对每个 `status=RUNNING` 的最新 attempt：

- `cli_subprocess` + pid 不存活 → `FAILED`（error_code=PROCESS_DEAD）
- `claude_tool` + last_seen_at 超 1800s 无信号 → `UNVERIFIED`（error_code=RUNNING_STALE_NO_SIGNAL），**不假定成功/失败**
- `dispatching` 超 600s 无 confirm-running → `UNVERIFIED`（error_code=DISPATCHING_TIMEOUT）

### 迟到通知与 attempt 隔离

- 旧 attempt（非 `latest_node_dispatch`）的迟到通知：记 `execution_events`，**不覆盖**最新 attempt 状态。
- 重复完成通知（DONE→DONE）：非法转换，被拒（幂等，状态不变）。
- 同 (node, attempt) 重复登记：`DuplicateExecutionError`，exit=4。
- 重试 = 新 attempt_id（新一行 node_dispatches），旧 attempt 状态保留不变。

### 恢复必做流程

```text
1. dispatch.py reconcile --project P --task-id T   # 对账僵尸/超时/迟到
2. dispatch.py plan --project P --task-id T        # 计算可执行节点（读 SQLite）
3. 对每个可执行节点：
   a. dispatch.py register-dispatch --node X --agent A --backend claude_tool
   b. 主控调用真实 Agent 工具（Python 不调）
   c. 拿到真实 agent_id → dispatch.py confirm-running --node X --attempt <id> --agent-id <real>
   d. Agent 返回 → dispatch.py record-result --node X --attempt <id> --status DONE|FAILED|BLOCKED
   e. 主控核验证据（规则4）→ 推进 DAG
4. dispatch.py export-state --project P --task-id T # 重建 run-state.json 只读快照
```

**禁止重复已完成节点**：DONE 节点不在 plan 可执行列表，不重跑。

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
