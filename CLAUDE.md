# zentao-dev-workflow：通用多 Agent 研发工作流（编排仓库）

本仓库是**通用研发工作流核心**：存放总控 Skill、专业 Subagents、工具适配器脚本和配置层。业务代码在各项目自己的仓库，通过 Git Worktree 修改。

> **通用性**：不写死任何项目名、人员账号、机器路径或 Jenkins Job。项目/人员/工具配置见 `config/`。

## 目录职责

| 目录 | 职责 | 归属 |
|---|---|---|
| `.claude/skills/zentao-dev-workflow/` | 总控 Skill（开发源） | 通用核心 |
| `.claude/agents/*.md` | 7 个专业 Subagents | 通用核心 |
| `config/workflow.yaml` | 全局执行策略 | 通用（无个人/项目信息） |
| `config/projects/{key}.yaml` | 项目属性：仓库/技术栈/Agent/集成 | 每项目 |
| `config/users/{id}.yaml` | 人员身份与偏好 | 每人（真实配置 gitignored） |
| `config/adapters/*.yaml` | 工具适配器非敏感配置 | 按工具 |
| `scripts/` | 工具适配器 + 配置加载器 | 通用核心 |
| `execution/{project_key}/{task_id}/` | 任务执行状态 | 每项目每任务 |
| `.env` | 机器级凭据 | 每人（gitignored） |

## 角色

- **Main Agent（本会话）**：唯一协调者。加载项目配置 → 获取任务 → 分派 Subagents → 复核交付 → 更新状态 → 进度回写 → 人工决策协调。
- **Subagents**：`.claude/agents/*.md`，各自只改自己所有权范围内的文件，返回结构化报告（见下）。

## 业务仓库（按项目配置，主工作区只读）

项目仓库路径由 `config/projects/{project_key}.yaml` 决定。**不得**假设业务仓库共存于同一父目录。

- 所有开发在 worktree（`config/workflow.yaml → worktree_root`），分支 `ai/zt-<task_id>`，基于各仓库指定基线分支。
- 遵守各业务仓库自身的 `CLAUDE.md` / `AGENTS.md`（Agent 必须先读目标仓库的 CLAUDE.md）。

## 状态文件（唯一可信状态源，不以聊天记录为准）

任务状态根：`execution/{project_key}/{task_id}/`

- `tasks.yaml`：任务 DAG（节点/依赖/Agent/文件所有权）
- `run-state.json`：阶段、节点状态、重试、阻塞、检查点
- `session.json`：Claude Session ID、集成会话 key（**不含 token**）
- `task-context.md`：任务上下文摘要
- `design/`、`acceptance/`、`agent-reports/`、`test-reports/`、`jenkins/`、`logs/`
- `audit.jsonl`：关键操作审计（任务写、CI 触发、人工决策），由 `scripts/audit.py` 追加

每个里程碑结束必须更新 `run-state.json` 与 `progress.md`。

## 硬约束

1. **任务系统**：经 `config/adapters/*.yaml` 启用的适配器访问（ZenTao / 其他）。只操作本人任务。字段编辑只用 PUT + 读回核验；进度**追加**不覆盖原文；不编造工时/日期/百分比；状态流转仅经适配器的正式动作端点；`task_finish` 经 Verifier 门禁后可自动执行并读回确认；**`task_close` 始终禁止自动执行**。
2. **CI**：只允许触发项目配置白名单内的 Job（`config/adapters/jenkins.yaml → jobs[]`，或项目配置的 `integrations.ci`）。部署 Job 一律禁止自动触发。结果以**最终 `result` + 测试报告**为准；FAILURE/ABORTED/NOT_BUILT 绝不判为通过；UNSTABLE 必须分析。
3. **人工决策**：经 `scripts/notify.sh`（通知适配器）发送，消息必须带 `project_key`、`task_id`、SessionID、BlockerID、阶段。设计未确认前不写业务代码。
4. **凭据**：不写入仓库、日志、文档、CI 参数。凭据只放 `.env`（gitignored）或用户级工具配置。
5. **如实报告**：测试未跑就说未跑，失败就贴失败；未执行标 `not_run` / `BLOCKED`，**不伪造结果**。
6. **不猜测**：缺项目/人员/适配器配置时明确报告缺失项，不自行猜测路径、账号、Job。

## 结构化 Agent 报告格式

`execution/{project_key}/{task_id}/agent-reports/<agent>-<seq>.json`：

```json
{
  "project_key": "…", "task_id": "…",
  "agent": "java-backend", "task_ids": ["B1"], "status": "done|blocked|failed",
  "worktree": "…", "branch": "…", "commit": "…",
  "files_changed": ["…"],
  "tests": [{"cmd": "…", "result": "pass|fail|not_run|blocked", "evidence": "…"}],
  "blockers": [{"id": "BLK-…", "level": "L1|L2|L3", "summary": "…"}],
  "notes": "…"
}
```

模板：`.claude/skills/zentao-dev-workflow/templates/agent-report.json`

## 问题分级与审批

- **L1** 编译错误/常规 Bug：Agent 自行修复。
- **L2** 多个可行技术方案：在已确认约束内自选，记 ADR 到 `execution/{project}/{task}/decisions.md`。
- **L3** 业务规则不清、DDL 重大变更、API 契约破坏、数据/权限风险、基础设施不可用：暂停受影响 Agent，写 run-state 阻塞，经通知渠道请求本人决策。

---

# Workflow Continuation Protocol（工作流续接协议）

> 以下为**硬性规则**。违反任一条即视为工作流执行失败。

## 规则 1：子 Agent 完成 ≠ 工作流完成

子 Agent 完成仅代表**当前 DAG 节点**完成，不代表整个工作流完成。

主 Agent **不得**仅因子 Agent 返回报告就停止执行。

## 规则 2：子 Agent 返回后的强制动作

每次子 Agent 返回后，主 Agent **必须**依次执行：

1. 读取 Agent Report
2. 校验报告内容与证据（不采信无证据的"完成"声明）
3. 检查代码、Commit、Worktree 实际状态
4. 更新任务 DAG 节点状态
5. 更新 `run-state.json`
6. 更新 `session.json`
7. 重新计算 DAG 可执行节点
8. 启动所有依赖条件已满足的节点
9. 记录本轮调度结果到 `run-state.json`

## 规则 3：DAG 自动推进

- 自动发现可执行节点
- 自动推进所有满足依赖条件的节点
- 独立任务合理并行
- **不得遗漏**可执行节点
- 单节点阻塞**不得**无理由停止其他独立节点

## 规则 4：完成状态验证

**不能**仅依据 Agent 自述就标记 DONE。

必须核验：报告 + 文件变更 + 测试证据 + Commit。

## 规则 5：人工审批

沿用 L1/L2/L3 风险等级：

- L1：自动处理
- L2：在已确认设计与授权范围内处理
- L3：通过配置的通知渠道请求本人确认

## 规则 6：中断恢复

每次恢复时**必须**：

1. 读取项目配置
2. 读取任务状态（`run-state.json` / `tasks.yaml`）
3. 读取最近 Agent Reports
4. 检查 Git 与 Worktree
5. 识别已完成 / 失败 / 阻塞 / 待执行节点
6. 从最近可信检查点继续

**禁止重复已验证完成的节点。**

## 规则 7：失败重试

- L1/L2 可自动修复
- 默认最多重试 **2** 次（`config/workflow.yaml → retry.max_attempts`）
- 每次重试记录原因与结果
- 超上限标记 `BLOCKED`
- L3 必须人工确认

## 规则 8：工作流结束

仅当**全部满足**才可标记工作流 `COMPLETED`：

1. 所有必需 DAG 节点完成
2. QA 与集成审查完成
3. 构建结果明确（真实结果，非推断）
4. 最终报告生成

**工作流完成 ≠ 业务任务关闭。**

**状态流转授权（2026-11-16 更新）**：
- `task_finish`（doing→done）：**Verifier 质量门禁通过后允许自动执行**；写入后必须读回禅道状态确认结果。
- `task_close`（→closed）：**始终禁止自动执行**，须本人在禅道手动操作。
