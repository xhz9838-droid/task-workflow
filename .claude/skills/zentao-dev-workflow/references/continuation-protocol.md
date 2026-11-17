# 续接协议（Continuation Protocol）

> 子 Agent 返回后主 Agent 的**强制动作**。对应 `CLAUDE.md` 规则 1-4。
> **状态唯一真相源 = agent-manager SQLite（`node_dispatches`）**。`run-state.json` 是 `dispatch.py export-state` 的只读快照。所有节点状态变更经 `dispatch.py`，禁止主控直接改 JSON。

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
④ dispatch.py record-result --node X --attempt <id> --status DONE|FAILED|BLOCKED
   （执行层结果写入 SQLite；不改 run-state.json）
⑤ 主控验收核验（规则4）通过 → 节点才算 DONE；不通过 → record-result UNVERIFIED
⑥ dispatch.py export-state（重建 run-state.json 只读快照）
⑦ dispatch.py plan（重新计算可执行节点，读 SQLite）
⑧ 启动所有可执行节点（独立节点并行）：register-dispatch → 主控调真实 Agent 工具 → confirm-running
⑨ 审计记录本轮调度（audit.py + execution_events）
```

> **关键**：步骤 ④ record-result 只记录**执行层**结果（Agent 跑完/跑挂）。步骤 ⑤ 是**验收层**——Agent 报告存在 ≠ 节点 DONE，必须证据核验（规则4）通过才标 DONE。两层分离，不混淆。

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

**不能**仅依据 Agent 自述标记 DONE。`record-result DONE` 只是执行层声明；节点真正 DONE 须主控验收核验通过：

| 核验项 | 方法 |
|---|---|
| 报告存在 | 文件存在且 JSON 合法 |
| 执行凭证 | SQLite `node_dispatches` 有对应 attempt_id + agent_id（非空） |
| 文件变更 | `git diff --stat` 与报告 `files_changed` 一致 |
| 测试证据 | `tests[]` 每项有 `result` + `evidence` |
| Commit | `git log` 能查到，message 格式正确 |
| 未越权 | 未修改 `files_changed` 之外的文件 |

**任一不满足 → `record-result UNVERIFIED`（不改 DONE），要求 Agent 补证据，不计入 DONE。**

## 处理 Agent 报告异常

| 情况 | 处理 |
|---|---|
| 报告缺失 | `record-result FAILED`（error_code=REPORT_MISSING），按重试策略 |
| 报告 JSON 非法 | 同上（error_code=REPORT_INVALID） |
| 声明 done 但无证据 | `record-result UNVERIFIED`，要求补证据 |
| 声明 done 但 worktree 无变更 | 同上 |
| 报告含越权修改 | 回退越权文件，`record-result FAILED`（L2），要求重做 |
| Agent 超时/卡住 | reconcile 标 UNVERIFIED/FAILED；主 Agent 接管执行该节点（不等死） |
| Agent 启动即失败（API 错误） | `record-result FAILED`（error_code 如 StreamNoEventsError）；TRANSIENT→新 attempt 重试，超上限 BLOCKED |
| 迟到通知（旧 attempt） | 记 execution_events，**不覆盖**最新 attempt 状态 |

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
