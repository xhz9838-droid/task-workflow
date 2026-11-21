---
name: zentao-dev-workflow
description: 通用多 Agent 研发工作流总控。按项目配置加载仓库/技术栈/Agent/工具适配器，执行需求分析→设计→DAG 调度→开发→测试→集成审查→人工审批→任务回写的完整流程。当用户提到"研发工作流"、"执行任务"、"跑工作流"、"/zentao-dev-workflow <项目> <任务>"、"继续工作流"、"恢复任务"、"推进 DAG"时使用。支持多人员、多项目、不同技术栈，可无 ZenTao/Jenkins 独立运行。
---

# zentao-dev-workflow：通用多 Agent 研发工作流总控

## 调用方式

```text
/zentao-dev-workflow {project_key} {task_id}                  # 单任务（历史方式，保持兼容）
/zentao-dev-workflow {project_key} {task_id} {task_id} ...    # 多任务
/zentao-dev-workflow {project_key} --tasks 3442,3443,3444     # 显式列表
/zentao-dev-workflow {task_id}                                # 仅任务号（如 #3415）：project_key 缺失，须归属验证
```

也支持自然语言（"用 jeebootx 项目跑任务 3413"、"继续上次的工作流"）。

参数**独立解析**（`scripts/_args.py parse`，Skill 与预检共用同一解析器）：

- `{task_id}`：纯数字，允许 `#` 前缀；多任务号自动去重，保持输入顺序
- `{project_key}`：非数字标识，对应 `config/projects/{project_key}.yaml`
- `project_key` 缺失时**不推断**：经统一项目解析链确定
  （`python -I "{WF}/scripts/zt.py" project --task <id>` 只读提取归属 →
  `python -I "{WF}/scripts/project_resolver.py" match --task-json -`）：
  project_id 精确 > product_id 辅助 > 显式映射 > 名称仅辅助（名称命中**须用户确认**）；
  唯一可靠命中才使用；多候选→询问用户；无命中→**不创建 execution**

`user_id` 是**可选**参数：普通任务启动、任务查询、Agent 调度不依赖它；
只有用户级仓库路径映射（`config/users/{id}.yaml → project_paths`）与
Human Decision 决策人校验在各自功能执行时才需要。

### 未注册项目（不要求用户重启命令）

显式 `project_key` 配置不存在，或 `match` 无命中时：

1. **不创建**正式 execution、**不派发** Agent；
2. 就地提示并执行 `/workflow-register-project`（或等价 CLI：
   `project_register.py plan ... --out ...` → 展示指纹 → `apply --plan ... --confirm <指纹>`）；
3. 注册完成后继续原任务。

## 第 0 步：定位工作流根（每次启动必做）

**Skill 安装目录只有 Skill 文件，不含 `scripts/`**。禁止尝试
`~/.claude/skills/zentao-dev-workflow/scripts/*.py`（必然不存在）。

按以下顺序取得 `{WF}`，不要猜：

1. 读取安装记录：`cat ~/.claude/zentao-dev-workflow.home`
2. `WORKFLOW_HOME` 环境变量
3. `~/.claude/zentao-dev-workflow.json` 的 `workflow_home`
4. 以上都无 → 进入工作流仓库目录运行 `python -I scripts/_home.py` 生成/确认

拿到候选后再复核：`python -I "{WF}/scripts/_home.py"`（输出校验通过的绝对路径）。
全部落空 → **明确报错**，提示设置 `WORKFLOW_HOME` 或重跑 `scripts/install.sh`；**不猜测**。

## 路径锚定

后续所有相对路径（`config/`、`execution/`、`scripts/`）均锚定**工作流根 `{WF}`**：

- `config/projects/{project_key}.yaml` = `{WF}/config/projects/{project_key}.yaml`
- `execution/{project_key}/{task_id}/` = `{WF}/execution/{project_key}/{task_id}/`
- 配置、执行状态、审计日志统一写 `{WF}/...`，按 `project_key/task_id` 隔离，
  不因启动目录不同产生重复或错位的状态目录

## 启动预检（统一入口，一次收集）

```bash
python -I "{WF}/scripts/preflight.py" {project_key} {task_id} [task_id ...] \
    [--tasks 3442,3443] [--user <id>] [--fetch-tasks] [--json] [--out <file>]
```

一次覆盖：工作流根、项目配置、项目上下文、仓库只读校验、任务参数、任务执行目录、
可选禅道任务详情、状态库/禅道 Skill/HITL MCP 运行环境。输出统一为
`PASS / WARN / BLOCKED + 原因 + 是否阻塞 + 已采取动作`：

- **WARN**（缺 user_id、工作区有未提交改动、首次执行无 tasks.yaml、任务详情获取失败等）
  → 记录后继续，不终止 Workflow；
- **BLOCKED**（工作流根无效、项目配置缺失、显式 user 下仓库路径不可用/Git 不一致、
  参数错误、`--require-tasks` 下任务详情失败）→ 必须先处理；
- 预检结果可 `--out` 落盘供后续阶段复用，避免重复检查。

不要将 Jenkins 构建/部署等非启动必要操作放进预检。**禁止**自行猜测：仓库路径、账号、Jenkins Job、任务字段。

## 多任务执行

预检通过后，用**既有** DAG/派发能力编排，不另建调度系统：

```bash
python -I "{WF}/scripts/dispatch.py" --project {project_key} \
    --task-ids {id1},{id2},{id3} batch-plan [--depends 3443:3442] [--parallel]
```

- `batch-plan` **只读**：不创建 execution、不派发、不改 run-state；输出每个任务
  的 DAG/状态/依赖与波次 `waves`。
- 依赖来源：任务 `tasks.yaml` 顶层 `depends_on_tasks` 或 `--depends A:B`；
  未声明依赖时**保持串行默认**，不擅自假定可并行；`--parallel` 仅表示同波次允许并行。
- 循环依赖、批次外未知依赖 → 报错，不进调度。
- 执行：按 `waves` 顺序推进；同一波次在 `--parallel` 下可并行，
  各任务仍走自己的 `execution/{project_key}/{task_id}/` 与 SQLite execution。
- 一个任务失败/`WAITING_HUMAN` **不得**阻塞其他独立任务；整体结束仍需逐任务
  `dispatch.py gate` 通过。每个任务独立回写进度、测试与验收结果。

## 执行流程

```text
0. 定位工作流根（第 0 步）→ 统一预检 preflight（项目/仓库/任务参数/执行目录；
   user_id 可选，缺省仅 WARN）→ 解析项目（显式 project_key 或任务自动发现：
   zt.py project → project_resolver match → context；未识别不创建 execution）
0.5 多任务：dispatch.py batch-plan（只读）→ 校验任务、识别依赖、输出 waves；
   单任务跳过。依赖未声明时串行默认，不擅自并行。
1. 加载配置（workflow → adapters → project → user → .env；仓库路径经 project_resolver）
2. 获取任务（task_source 适配器；无适配器则从 task-context.md / 人工输入）
3. 需求分析（architect，读任务描述 + 项目代码 + 项目 CLAUDE.md）
4. 技术设计（architect / database，产出 design/）
5. 设计确认（L2 自主 / L3 人工）：L2 在授权内自决并写入 decisions.md，**不调用 HITL**；仅 L3 必须通过 `mcp__human-decision__request_human_decision` 发起（禁止对话直接询问）。有界等待 300s，超时 → suspended → 挂起依赖节点，独立节点继续。权限拦截 → 记录待授权事件到 decisions.md，不阻塞主流程。
6. 生成任务 DAG（tasks.yaml）+ migrate_runstate.py（历史 run-state 迁入 SQLite）
7. Agent 调度（dispatch.py plan/register-dispatch/confirm-running；按 agents{} 过滤启用项）
8. 开发 + 测试（各 Agent 在 worktree 内，遵守文件所有权）
9. CI 构建（jenkins 适配器，仅白名单 Job）
10. 失败修复（L1/L2 自动，L3 人工）；dispatch.py reconcile 对账僵尸/超时
11. QA + 集成审查（dispatch.py record-result 写执行层结果，主控验收层核验）
12. 进度回写（task_source 适配器，追加不覆盖；`pending_writes` 非空时先 flush）
13. 最终报告 → Verifier 门禁通过 → **`dispatch.py gate --finalize` 返回 ok** → 自动 task_finish（读回确认；**须带完成内容 + git commit id**，写入 finished 动作备注，不写任务 desc）→ 关闭条件满足则自动 task_close（读回确认）
```

> **状态源**：DAG 节点执行状态唯一真相源是 agent-manager SQLite（`node_dispatches`）。`run-state.json` 是 `dispatch.py export-state` 的只读快照。主控/Skill/Subagent 禁止直接改 JSON。
>
> **阶段进度自动回写**：每个阶段（需求分析、技术设计、人工设计确认、开发+测试、QA+集成审查）完成后自动调用 Zentao Reporter 追加进度（`report_progress`），不等待用户确认。回写失败入 `pending_writes` 队列，后续重试。

## L3 决策强制路由

1. 任何 L3 级决策（设计确认、DDL 变更、API 契约破坏等）必须通过 `mcp__human-decision__request_human_decision` MCP 工具发起
2. 禁止在对话中直接询问用户代替 L3 决策流程
3. 调用后使用 `wait_for_decision` 模型（有界等待 300s），超时 → outcome=suspended → 挂起当前节点，继续独立节点
4. 权限拦截 → 记录待授权事件到 decisions.md，不等死

## 核心规则

**严格遵守 `CLAUDE.md` 的 Workflow Continuation Protocol（8 条硬规则）**，尤其：

- **规则 1/2/3**：子 Agent 完成后必须继续推进 DAG，不得提前结束
- **规则 4**：完成状态须证据核验，不采信 Agent 自述
- **规则 6**：中断恢复从最近可信检查点继续，不重复已完成节点
- **规则 8**：结束前必须运行 `python -I "{WF}/scripts/dispatch.py" --project <k> --task-id <id> gate --finalize`，返回 ok 才允许 COMPLETED；`task_finish` 经 Verifier 门禁后自动执行（须读回确认，**且须带完成内容 + git commit id**，写入 finished 动作备注、不写任务 desc）；`task_close` 在关闭条件满足后自动执行（须读回确认），条件不满足则暂缓并记录原因。

## 何时查阅 references

| 场景 | 文件 |
|---|---|
| 流程各阶段输入输出、产物位置 | `references/workflow-lifecycle.md` |
| 子 Agent 返回后的强制动作、DAG 推进 | `references/continuation-protocol.md` |
| 中断恢复、检查点、状态核验 | `references/recovery-protocol.md` |
| L1/L2/L3 分级与人工审批 | `references/approval-policy.md` |
| Agent 启用过滤、并行调度、报告格式 | `references/agent-dispatch.md` |
| 项目配置加载、技术栈适配、无适配器运行 | `references/project-adaptation.md` |
| 重大决策人工介入（P0/P1/P2、阻塞等待、钉钉回复、Session 恢复） | `references/human-decision-policy.md` |
| 发版流程（计划→门禁→白名单构建→报告→禅道回写；部署 Job 禁自动触发） | `references/release-process.md` |

## templates

| 文件 | 用途 |
|---|---|
| `templates/tasks.yaml` | 任务 DAG 模板 |
| `templates/run-state.json` | 执行状态模板 |
| `templates/session.json` | 会话上下文模板 |
| `templates/agent-report.json` | Agent 报告模板 |

## 跨项目与个人级安装

开发源：`{WORKFLOW_HOME}/.claude/skills/zentao-dev-workflow/`
安装目标：`~/.claude/skills/zentao-dev-workflow/`

```bash
{WORKFLOW_HOME}/scripts/install.sh          # 安装/更新 Skill + Agents 到个人级，写入安装记录
{WORKFLOW_HOME}/scripts/install.sh --uninstall
```

安装会写入安装记录 `~/.claude/zentao-dev-workflow.home`（工作流仓库绝对路径），
供第 0 步从任意目录定位工作流根。

在**任意项目根目录**启动 Claude Code 后即可调用：
```text
/zentao-dev-workflow {project_key} {task_id}
```

Skill 按 `project_key` 加载项目配置，按 `task_id` 加载任务状态，**不依赖当前项目目录存在工作流 Skill**。

## 重要约束

- 不写死项目名、人员账号、机器路径、Jenkins Job、任务 ID
- 不在 Skill / Agent / 脚本中写入凭据
- 不假设所有业务仓库共存同一父目录
- 不假设每个项目都需要全部 7 个 Agent
- 不自动执行部署、服务重启、任务关闭
- 缺配置时**报缺失项**，不猜测、不编造默认值
- `user_id` 不是普通启动的必要条件：缺省时 WARN 继续；不得因此阻止项目解析、
  任务查询、Agent 调度与普通研发执行。身份相关的校验（决策人白名单）只在其功能执行时检查
- 多任务不得合并成单任务；参数错误必须给出明确原因与正确用法
- 无 ZenTao / Jenkins 配置时，仍可执行需求分析、开发、测试、代码审查、状态管理
- **禁止无条件自行结束工作流**。结束前必须检查：(1) 所有 DAG 节点处于终态（DONE/FAILED/CANCELLED）；(2) 无待处理 Human Decision（WAITING_HUMAN 节点）；(3) 无 pending_writes 未刷写。任一不满足 → 继续推进。
