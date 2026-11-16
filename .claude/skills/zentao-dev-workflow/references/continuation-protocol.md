# 续接协议（Continuation Protocol）

> 子 Agent 返回后主 Agent 的**强制动作**。对应 `CLAUDE.md` 规则 1-4。

## 规则 1：子 Agent 完成 ≠ 工作流完成

子 Agent 完成仅代表**当前 DAG 节点**完成。主 Agent 不得据此停止整个工作流。

## 规则 2：子 Agent 返回后的 9 步强制动作

每次子 Agent 返回后，**必须**依次执行：

```text
① 读取 Agent Report（execution/{project}/{task}/agent-reports/<agent>-<seq>.json）
② 校验报告内容与证据
   - tests[].result 是否有 evidence
   - 声明 "done" 但无文件变更/无测试证据 → 标记为 unverified，要求补证据
   - 不采信无证据的完成声明
③ 检查实际状态
   - git log：commit 是否存在
   - git diff：文件变更是否与报告一致
   - worktree 状态：分支、脏文件
④ 更新 DAG 节点状态（tasks.yaml 或 run-state.dag.nodes[]）
⑤ 更新 run-state.json（阶段、节点状态、updated_at）
⑥ 更新 session.json（如涉及会话/worktree/集成变化）
⑦ 重新计算 DAG 可执行节点（依赖已满足 且 未完成 且 未阻塞）
⑧ 启动所有可执行节点（独立节点并行）
⑨ 记录本轮调度结果到 run-state.json → checkpoints[]
```

## 规则 3：DAG 自动推进

- **自动发现**可执行节点，不等人工触发
- **自动推进**所有依赖满足的节点
- 独立任务**合理并行**
- **不得遗漏**可执行节点
- 单节点阻塞**不得**无理由停止其他独立节点

### 可执行节点判定

```text
可执行(node) =
  node.status == pending
  AND ∀ dep ∈ node.dependencies: dep.status == done
  AND node.agent 在 projects/{key}.yaml → agents{} 启用
  AND node 未被 L3 阻塞
```

### 并行度

受 `config/workflow.yaml → concurrency.max_parallel_agents` 约束（默认 2）。

## 规则 4：完成状态验证

**不能**仅依据 Agent 自述标记 DONE。必须核验：

| 核验项 | 方法 |
|---|---|
| 报告存在 | 文件存在且 JSON 合法 |
| 文件变更 | `git diff --stat` 与报告 `files_changed` 一致 |
| 测试证据 | `tests[]` 每项有 `result` + `evidence` |
| Commit | `git log` 能查到，message 格式正确 |
| 未越权 | 未修改 `files_changed` 之外的文件 |

**任一不满足 → 节点标记 `unverified`，要求 Agent 补证据，不计入 DONE。**

## 处理 Agent 报告异常

| 情况 | 处理 |
|---|---|
| 报告缺失 | 记录 BLOCKED，要求 Agent 重跑或主 Agent 自行执行该节点 |
| 报告 JSON 非法 | 同上 |
| 声明 done 但无证据 | 标 `unverified`，要求补证据 |
| 声明 done 但 worktree 无变更 | 同上 |
| 报告含越权修改 | 回退越权文件，记录 L2，要求重做 |
| Agent 超时/卡住 | 主 Agent 接管执行该节点（不等死） |

## Agent 报告格式

```json
{
  "project_key": "…", "task_id": "…",
  "agent": "java-backend", "task_ids": ["B1"], "status": "done|blocked|failed|unverified",
  "worktree": "…", "branch": "…", "commit": "…",
  "files_changed": ["…"],
  "tests": [{"cmd": "…", "result": "pass|fail|not_run|blocked", "evidence": "…"}],
  "blockers": [{"id": "BLK-…", "level": "L1|L2|L3", "summary": "…", "wait_for": "…", "resume_steps": "…"}],
  "cross_checks": {…},
  "verdict": "PASS|PARTIAL|FAIL",
  "notes": "…"
}
```

模板：`templates/agent-report.json`
