# Agent 调度（Agent Dispatch）

> 对应 `CLAUDE.md` 规则 3。Agent 启用过滤、并行调度、报告格式。

## 7 个基础 Subagents

| Agent | 通用职责 | 典型适用 |
|---|---|---|
| `architect` | 需求分析、架构设计、任务拆解 | 所有项目 |
| `database` | 数据库与数据层设计 | 有持久化层 |
| `java-backend` | Java 后端开发 | Java/Spring |
| `web-frontend` | Web 前端开发 | Web |
| `mobile-app` | 移动端开发 | 移动端 |
| `qa-engineer` | 测试与质量保障 | 所有项目 |
| `integration-reviewer` | 集成审查与代码质量 | 多端/多仓库 |

**7 个是基础角色集合，不是固定流程。** 不适用的 Agent 不启用。

## 启用过滤

来自 `config/projects/{project_key}.yaml → agents{}`：

```yaml
agents:
  architect: true
  database: false          # 无数据库则关闭
  java-backend: true
  web-frontend: true
  mobile-app: false        # 无移动端则关闭
  qa-engineer: true
  integration-reviewer: true
```

### 示例组合

| 项目类型 | 启用 Agent |
|---|---|
| Java + Vue | architect, database, java-backend, web-frontend, qa-engineer, integration-reviewer |
| Python + React | architect, python-backend*, web-frontend, qa-engineer, integration-reviewer |
| 纯前端 | architect, web-frontend, qa-engineer |
| 纯后端 | architect, database, java-backend, qa-engineer |
| 移动端 | architect, mobile-app, qa-engineer |

> *`python-backend` 等技术栈 Agent 可通过新增 `.claude/agents/{tech}-*.md` 扩展，不强制 7 个。

## 技术栈知识来源

Agent 定义**保持通用**。技术栈特定知识通过：

1. **项目内 `CLAUDE.md` / `AGENTS.md`**（Agent 提示中显式要求先读）
2. **项目配置** `config/projects/{key}.yaml → tech_stack{}`、`build{}`、`repositories[]`
3. **设计产物** `design/openapi.yaml`、`design/ddl.sql`

**禁止**把某技术栈写死进通用 Agent 定义。

## 调度策略

```text
可执行(node) =
  node.status == pending
  AND ∀ dep ∈ node.dependencies: dep.status == done
  AND node.agent 在 agents{} 启用
  AND node 未被 L3 阻塞
```

- **并行度**：`config/workflow.yaml → concurrency.max_parallel_agents`（默认 2）
- **独立节点并行**，依赖节点串行
- **文件所有权**：`tasks.yaml → nodes[].files[]`，不同 Agent 不同文件
- **冲突处理**：两 Agent 需改同一文件 → L2 决策（合并任务或串行）

## Agent 提示要求

派发 Agent 时**必须**包含：

```text
1. project_key / task_id / 当前阶段
2. 目标产物（files_changed / 交付物）
3. 依赖的设计产物路径（design/*）
4. worktree 路径与分支
5. 文件所有权（只改分配文件）
6. 目标仓库的 CLAUDE.md / AGENTS.md 位置（先读）
7. 报告输出路径（execution/{project}/{task}/agent-reports/<agent>-<seq>.json）
8. 硬约束（不伪造结果、不越权、不触发 CI、不操作任务系统）
9. 测试要求（真实执行，未跑标 not_run）
```

## Agent 报告格式

见 `templates/agent-report.json` 与 `references/continuation-protocol.md`。

**关键字段**：
- `status`: `done | blocked | failed | unverified`
- `tests[].result`: `pass | fail | not_run | blocked`
- `blockers[].level`: `L1 | L2 | L3`
- `verdict`: `PASS | PARTIAL | FAIL`

**规则**：
- 无法真实验证的项标 `blocked` 并写 `reason` / `wait_for` / `resume_steps`
- **不得**把未执行的测试标为 `pass`
- 越权修改 → 回退并记录

## Agent 超时/卡住处理

- Agent 运行超过合理时间无输出 → 主 Agent **接管执行该节点**
- 不等死、不无限等待
- 接管后记录到 `run-state.checkpoints[]`

## 扩展新 Agent

新增 `.claude/agents/{name}.md`：

```markdown
---
name: {name}
description: {职责描述}
tools: Read, Grep, Glob, Bash, Write, Edit
---
# {name}
## 职责
## 文件所有权
## 测试责任
## 通用规则（含报告格式与硬约束）
```

并在 `config/projects/*.yaml → agents{}` 中按需启用。
