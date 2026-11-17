---
name: zentao-dev-workflow
description: 通用多 Agent 研发工作流总控。按项目配置加载仓库/技术栈/Agent/工具适配器，执行需求分析→设计→DAG 调度→开发→测试→集成审查→人工审批→任务回写的完整流程。当用户提到"研发工作流"、"执行任务"、"跑工作流"、"/zentao-dev-workflow <项目> <任务>"、"继续工作流"、"恢复任务"、"推进 DAG"时使用。支持多人员、多项目、不同技术栈，可无 ZenTao/Jenkins 独立运行。
---

# zentao-dev-workflow：通用多 Agent 研发工作流总控

## 调用方式

```text
/zentao-dev-workflow {project_key} {task_id}
/zentao-dev-workflow {task_id}            # 仅任务号（如 #3415）：project_key 缺失，须归属验证
```

也支持自然语言（"用 jeebootx 项目跑任务 3413"、"继续上次的工作流"）。

参数**独立解析**（`scripts/_args.py parse`）：

- `{task_id}`：纯数字，允许 `#` 前缀；`#3415` 只是任务号，**不是完整参数**
- `{project_key}`：非数字标识，对应 `config/projects/{project_key}.yaml`
- `project_key` 缺失时**不推断**：经统一项目解析链确定
  （`python -I "{WF}/scripts/zt.py" project --task <id>` 只读提取归属 →
  `python -I "{WF}/scripts/project_resolver.py" match --task-json -`）：
  project_id 精确 > product_id 辅助 > 显式映射 > 名称仅辅助（名称命中**须用户确认**）；
  唯一可靠命中才使用；多候选→询问用户；无命中→提示 `/workflow-register-project`，**不创建 execution**

## 第 0 步：定位工作流根（每次启动必做）

Skill 安装目录（本 SKILL.md 所在目录）**只有 Skill 文件**，不含 `config/`、`execution/`，
**不得**当作工作流仓库；当前业务项目目录同样**不得**当作工作流根。

统一解析机制（`scripts/_home.py`，优先级命中即止）：

1. 环境变量 `WORKFLOW_HOME`
2. 用户级配置 `~/.claude/zentao-dev-workflow.json` → `workflow_home`
3. 安装记录 `~/.claude/zentao-dev-workflow.home`（`scripts/install.sh` 写入）
4. Skill 开发源（脚本所在仓库，须通过校验）
5. 从当前目录向上探测（须同时含 `config/workflow.yaml` + `scripts/_config.py`）

按上述顺序取得候选目录 `{WF}` 后复核：

```bash
python -I "{WF}/scripts/_home.py"          # 输出校验通过的工作流根绝对路径
```

全部落空 → **明确报错**并列出已尝试来源，询问用户设置 `WORKFLOW_HOME`；**不猜测**。

## 路径锚定

后续所有相对路径（`config/`、`execution/`、`scripts/`）均锚定**工作流根 `{WF}`**：

- `config/projects/{project_key}.yaml` = `{WF}/config/projects/{project_key}.yaml`
- `execution/{project_key}/{task_id}/` = `{WF}/execution/{project_key}/{task_id}/`
- 配置、执行状态、审计日志统一写 `{WF}/...`，按 `project_key/task_id` 隔离，
  不因启动目录不同产生重复或错位的状态目录

## 启动前必检（缺任一项**明确报错**，不猜测）

1. **项目解析**：`python -I "{WF}/scripts/project_resolver.py" context --project <key> --user <id>`
   （未注册/禁用 → 提示 `/workflow-register-project`，不创建 execution）
2. **项目路径**：`config/users/{id}.yaml → project_paths` 优先于 `repositories[].path`（`${ENV}` 展开）；
   仓库校验经 `scripts/repo_check.py`（`blocked`/`mismatch` → 列出问题交用户处理，不自动修复）
3. **人员配置**：`config/users/{user_id}.yaml` 存在（或 `--user` 显式指定）
4. **工具适配器**：按项目 `integrations.*` 判断需要哪些适配器，检查 `config/adapters/*.yaml`
5. **任务来源**：`integrations.task_source` 明确（zentao / none）
6. **当前身份与权限**：适配器能确认当前用户身份

**禁止**自行猜测：仓库路径、账号、Jenkins Job、任务字段。

## 执行流程

```text
0. 定位工作流根（第 0 步）→ 解析项目（显式 project_key 或任务自动发现：
   zt.py project → project_resolver match → context；未识别不创建 execution）
1. 加载配置（workflow → adapters → project → user → .env；仓库路径经 project_resolver）
2. 获取任务（task_source 适配器；无适配器则从 task-context.md / 人工输入）
3. 需求分析（architect，读任务描述 + 项目代码 + 项目 CLAUDE.md）
4. 技术设计（architect / database，产出 design/）
5. 人工设计确认（通知渠道；未确认不进编码）
6. 生成任务 DAG（tasks.yaml）+ migrate_runstate.py（历史 run-state 迁入 SQLite）
7. Agent 调度（dispatch.py plan/register-dispatch/confirm-running；按 agents{} 过滤启用项）
8. 开发 + 测试（各 Agent 在 worktree 内，遵守文件所有权）
9. CI 构建（jenkins 适配器，仅白名单 Job）
10. 失败修复（L1/L2 自动，L3 人工）；dispatch.py reconcile 对账僵尸/超时
11. QA + 集成审查（dispatch.py record-result 写执行层结果，主控验收层核验）
12. 进度回写（task_source 适配器，追加不覆盖）
13. 最终报告 → Verifier 门禁通过 → 自动 task_finish（读回确认）→ **不自动 task_close**
```

> **状态源**：DAG 节点执行状态唯一真相源是 agent-manager SQLite（`node_dispatches`）。`run-state.json` 是 `dispatch.py export-state` 的只读快照。主控/Skill/Subagent 禁止直接改 JSON。

## 核心规则

**严格遵守 `CLAUDE.md` 的 Workflow Continuation Protocol（8 条硬规则）**，尤其：

- **规则 1/2/3**：子 Agent 完成后必须继续推进 DAG，不得提前结束
- **规则 4**：完成状态须证据核验，不采信 Agent 自述
- **规则 6**：中断恢复从最近可信检查点继续，不重复已完成节点
- **规则 8**：工作流 COMPLETED 前需全部节点完成 + QA + 集成审查 + 真实构建结果 + 最终报告；`task_finish` 经 Verifier 门禁后可自动执行（须读回确认）；**`task_close` 始终禁止自动**

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
- 无 ZenTao / Jenkins 配置时，仍可执行需求分析、开发、测试、代码审查、状态管理
