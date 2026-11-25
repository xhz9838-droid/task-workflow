# 工作流生命周期（Workflow Lifecycle）

> 定义各阶段的输入、输出、产物位置与退出条件。

## 配置加载（阶段 0）

**输入**：`project_key`、`task_id`
**第 0 步**：定位工作流根 `{WF}`（`scripts/_home.py`，见 project-adaptation.md）；
以下 `config/`、`execution/` 等相对路径均锚定 `{WF}`。
**加载顺序**（后者覆盖前者）：

1. 脚本内置默认值
2. `config/workflow.yaml`
3. `config/adapters/{name}.yaml`
4. `config/projects/{project_key}.yaml`
5. `config/users/{user_id}.yaml`
6. `.env`

**输出**：合并后的配置对象（`scripts/_config.py → load_config()`）
**退出条件**：项目配置存在、仓库路径有效、所需适配器已配置

## 任务获取（阶段 1）

| 来源 | 适配器 | 产物 |
|---|---|---|
| ZenTao | `scripts/zt.py` | `task-context.md`（任务名/描述/状态/优先级/项目/迭代/工时字段） |
| 其他任务系统 | 按 `integrations.task_source` | 同上 |
| 无适配器 | 人工输入 | `task-context.md` |

**规则**：
- 只操作本人任务（适配器需确认身份）
- 只读不写（本阶段）
- 缺失字段标"未提供"，**不猜测**
- 任务已 `done`/`closed` → 报告并停止，不重复执行

## 需求分析（阶段 2）

**Agent**：`architect`
**输入**：`task-context.md` + 项目仓库代码 + 各仓库 `CLAUDE.md`/`AGENTS.md`
**产物**：`execution/{project}/{task}/design/requirements.md`
**内容**：业务功能、流程、角色权限、数据实体、API、页面（Web/Mobile）、性能安全约束、异常场景、验收标准

**规则**：不擅自增加未确认需求；结论标注证据（文件:行号）；推测标"推测"

## 技术设计（阶段 3）

**Agent**：`architect` + `database`（如启用）
**产物**：`design/architecture.md`、`design/ddl.sql`、`design/openapi.yaml`、`design/migrations/`、`design/data-dictionary.md`
**规则**：
- **优先复用**现有能力/状态字段/接口，不重新设计已有流程
- 与现有系统兼容；不无依据重设计架构
- 发现契约需变更 → L3 阻塞

## 人工设计确认（阶段 4）

**通知**：`scripts/notify.sh`
**消息**：含 `project_key`、`task_id`、SessionID、BlockerID、阶段
**退出条件**：收到明确确认（L3 项须逐项决策）
**未确认 → 不进编码**

## 任务 DAG 生成（阶段 5）

**产物**：`execution/{project}/{task}/tasks.yaml`
**内容**：节点（id/agent/依赖/文件所有权/交付物/验收项）
**规则**：
- 按模块/功能划分，每节点独立交付物
- 明确文件所有权（不同 Agent 不同文件）
- 公共接口冻结后再开发
- 按 `projects/{key}.yaml → agents{}` 过滤启用 Agent

## Agent 调度（阶段 6）

见 `references/agent-dispatch.md`

## 开发 + 测试（阶段 7）

**约束**：
- 只在 worktree 内修改（主工作区只读）
- 只改分配文件
- 遵循冻结的 DDL/OpenAPI
- 编写并运行测试（结果真实）
- `git diff` 自检、commit（不 push 除非指示）

## CI 构建（阶段 8）

**适配器**：`scripts/jenkins_run.py`（或其他）
**规则**：
- **仅白名单 Job**（`config/adapters/jenkins.yaml → jobs[]`）
- 部署 Job 一律禁止自动触发
- 状态判断以**最终 `result` + 测试报告**为准
- FAILURE/ABORTED/NOT_BUILT 绝不判为通过；UNSTABLE 必须分析
- CI 不可达/认证失败 → L3，**不回退其他 CI**

## 失败修复（阶段 9）

| 等级 | 处理 |
|---|---|
| L1 | Agent 自行修复，重试 ≤ `retry.max_attempts` |
| L2 | 约束内自选方案，记 ADR |
| L3 | 暂停 + 人工决策 |

## QA + 集成审查（阶段 10）

**Agent**：`qa-engineer` + `integration-reviewer`
**产物**：`acceptance/acceptance-matrix.md`（结论）、`agent-reports/qa-engineer-*.json`
**规则**：
- 无法真实验证的项标 `BLOCKED` 并写原因/等待条件/恢复步骤
- 跨端契约一致性核对
- 联调结论必须基于**实际运行证据**

## 工作日志 / 工时（阶段 11）

**工具**：`scripts/worklog.py`（计算） + `scripts/zt.py worklog`（写入）

**触发**（按实际交付里程碑，不按时间/Agent 数/文件数）：
- 开发 + 测试完成一个完整模块或阶段；
- QA + 集成审查完成；
- 最终满足完成条件、`finish` 之前（必须 100%）。
- 小任务只有一个交付阶段 → 只在最终 `finish` 前记一次。

```bash
python -I "{WF}/scripts/zt.py" worklog --task <id> --stage dev   --progress 50 --work "完成设备围栏页面；实现启用/停用；前端构建通过；修复默认值问题"
```

**规则**：
- 总工时：计划周期工作日（周一至周五）× 8，其次 `estimate`；都可缺 → `NO_BASELINE`，不编造；
  需要时由人提供 `--total-hours`。
- `consumed` 是本次增量 = 总工时×进度 − 任务当前 consumed；`left` = 总工时 − 总工时×进度。
- 同一进度/Agent 重试 → 自动跳过，不重复累计。
- 工作日志**不改变任务状态**；完成仍走 Verifier 门禁 + `finish`。
- 失败/结果不明 → 先查任务是否已写入再重试；**最终工作日志未成功不得 finish**。

## 进度回写（阶段 11）

**适配器**：`scripts/zt.py`（或对应适配器）
**规则**：
- **追加**不覆盖原文
- 不编造工时/日期/百分比
- 不擅自改负责人/计划时间/工时
- 写回失败先查详情防重复

## 最终报告（阶段 12）

**产物**：`execution/{project}/{task}/final-report.md`
**内容**：任务 ID、Workflow ID、分支/commit、各 Agent 交付、CI Build URL、测试报告、未完成事项、人工决策记录、验收结果

## 人工确认 → 停止

**状态流转授权（2026-11-16 更新）**：
- `task_finish`（doing→done）：Verifier 质量门禁通过后**允许自动执行**，**必须带完成内容 + git commit id**（写入 finished 动作备注，不写任务 desc），写入后**必须读回禅道状态与完成备注确认结果**
- `task_close`（→closed）：**始终禁止自动执行**，须本人手动操作

工作日志的 `consumed`/`left` 由 `scripts/worklog.py` 依据进度与基线计算；`finish` 的 `consumed`/`left`/`finishedDate` 仍必须由调用方提供。
工作流标记 `COMPLETED` ≠ 业务任务关闭。
