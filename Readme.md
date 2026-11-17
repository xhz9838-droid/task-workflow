# Agent 智能研发工作流平台
## 产品说明与内部使用手册

| 文档属性 | 内容 |
|---|---|
| 产品名称 | Agent 智能研发工作流平台（Agent Development Workflow） |
| 文档版本 | V1.0 |
| 文档日期 | 2026-11-17 |
| 使用对象 | 公司研发人员、技术负责人、项目负责人、平台维护人员 |
| 核心运行环境 | Windows 11、Git Bash、Claude Code、Python 3.13 |
| 工作流入口 | `/zentao-dev-workflow` |
| 当前实现状态 | 通用化框架已完成，HITL 核心能力已完成验收 |

---

# 第一章 产品介绍

## 1.1 产品定位

Agent 智能研发工作流平台是一套基于 Claude Code 的多 Agent 软件研发协作框架。

平台通过一个总控 Skill 组织多个专业 Agent，将需求分析、技术设计、任务拆解、代码开发、测试验证、代码审查、构建检查和结果报告串联成标准化研发流程。

它不是简单的 AI 代码补全工具，而是一个具备任务状态管理、并行执行、失败检测、人工决策和中断恢复能力的研发工作流系统。

平台采用通用核心架构，将研发流程、项目配置、人员配置和外部工具适配器分离，使不同人员能够使用自己的账号，在不同技术栈和不同业务项目中复用同一套研发工作流。

## 1.2 建设目标

平台主要解决以下问题：

1. **研发流程标准化**：将需求分析、开发、测试、审查和交付形成统一流程。
2. **专业化 Agent 分工**：由不同专业 Agent 处理不同类型的研发工作。
3. **任务自动编排**：根据任务依赖关系构建 DAG，自动启动满足条件的工作节点。
4. **跨项目复用**：支持不同项目、不同仓库、不同技术栈。
5. **跨人员复用**：每位研发人员使用自己的账号、凭据和项目权限。
6. **外部工具集成**：可接入禅道、Jenkins、钉钉等外部系统。
7. **人工决策闭环**：遇到需要人工批准的操作时，暂停任务并通知决策人。
8. **异常检测和恢复**：识别 Agent 失败、超时和中断，支持重试及会话恢复。
9. **过程可审计**：记录任务状态、Agent 报告、Git 变更和执行证据。

## 1.3 适用场景

- 禅道需求或缺陷的自动化研发处理。
- Spring Boot、Vue、React、Python、移动端等项目的开发。
- 多仓库协同开发。
- 代码修改后的自动测试和质量审查。
- 需要人工审批的高风险研发操作。
- 长时间运行、可能中断的复杂研发任务。
- 多人共用统一研发规范的团队。

## 1.4 产品边界

平台当前定位为研发辅助与研发流程编排系统。

平台可以根据授权执行代码修改、测试、Git 操作、任务状态查询和构建检查，但不代表可以无条件执行所有生产操作。

以下操作仍受到授权边界约束：

- 不自动部署业务系统。
- 不自动重启业务服务。
- 不自动执行禅道 `task_finish` 或 `task_close`。
- 不绕过人工审批执行 L3 高风险操作。
- 不将个人账号、Token、密码等凭据提交到 Git。
- 不以 Agent 自述作为任务完成的唯一证据。

---

# 第二章 整体架构

## 2.1 架构设计

平台采用：

**通用工作流核心 + 项目配置 + 人员配置 + 工具适配器 + 独立任务执行状态 + HITL 人工决策。**

整体结构：

```text
研发人员
   |
   v
Claude Code
   |
   v
/zentao-dev-workflow
   |
   v
总控 Skill
   |
   +---------------------------+
   |      工作流调度器         |
   |                           |
   |  需求分析 / DAG / 状态管理 |
   |  并行执行 / 失败恢复      |
   +---------------------------+
       |
       +--------+--------+--------+
       |        |        |        |
       v        v        v        v
    Architect Database Backend  Frontend
       |        |        |        |
       +--------+--------+--------+
                |
         QA / Integration
                |
                v
          结果验证与报告
                |
     +----------+----------+
     |          |          |
     v          v          v
   ZenTao    Jenkins    DingTalk
     |          |          |
     +----------+----------+
                |
                v
          HITL 人工决策
                |
                v
          任务状态与审计
```

## 2.2 核心模块

| 模块 | 主要职责 |
|---|---|
| 总控 Skill | 工作流入口、任务理解、调度和生命周期管理 |
| Subagents | 专业领域分析、开发、测试与审查 |
| 配置加载器 | 读取全局、人员、项目和适配器配置 |
| 工具适配器 | 对接禅道、Jenkins、通知系统 |
| 状态管理 | 保存任务 DAG、运行状态、Agent 报告 |
| HITL | 人工决策请求、身份校验、阻塞和恢复 |
| 审计模块 | 记录执行过程、状态变更和证据 |
| 安装程序 | 将 Skill 和 Agent 安装到个人 Claude Code 环境 |

## 2.3 仓库目录结构

当前工作流仓库：

`D:\WorkSpace\task-workflow`

主要目录：

```text
task-workflow/
│
├── .claude/
│   ├── skills/
│   │   └── zentao-dev-workflow/
│   │       ├── SKILL.md
│   │       ├── references/
│   │       └── templates/
│   │
│   └── agents/
│       ├── dw-architect.md
│       ├── dw-database.md
│       ├── dw-java-backend.md
│       ├── dw-web-frontend.md
│       ├── dw-mobile-app.md
│       ├── dw-qa-engineer.md
│       └── dw-integration-reviewer.md
│
├── config/
│   ├── workflow.yaml
│   ├── users/
│   ├── projects/
│   └── adapters/
│
├── scripts/
│   ├── _config.py
│   ├── zt.py
│   ├── jenkins_run.py
│   ├── notify.sh
│   ├── audit.py
│   └── install.sh
│
├── agent-manager/
│   └── human_decision/
│
├── execution/
│   ├── jeebootx/
│   │   └── 3413/
│   └── demo-react/
│       └── 1001/
│
└── docs/
```

说明：

- `.claude/skills/`：总控工作流定义。
- `.claude/agents/`：专业 Agent 定义。
- `config/`：工作流、人员、项目及适配器配置。
- `scripts/`：工具适配和自动化脚本。
- `agent-manager/human_decision/`：HITL 人工决策管理模块。
- `execution/`：每个项目、每个任务独立的执行状态和证据。

---

# 第三章 Agent 角色说明

平台提供七个基础专业 Agent。

Agent 可以根据项目技术栈动态启用，不要求每个项目必须使用全部七个 Agent。

| Agent | 职责 | 主要工作 |
|---|---|---|
| architect | 架构设计 | 需求分析、技术方案、任务拆解、依赖规划 |
| database | 数据库 | 表结构、DDL、SQL、索引、数据兼容性 |
| java-backend | Java 后端 | Spring Boot、接口、业务逻辑、持久层 |
| web-frontend | Web 前端 | Vue、React、页面、组件、接口集成 |
| mobile-app | 移动端 | uni-app、移动端页面和接口 |
| qa-engineer | 测试 | 功能测试、接口测试、回归测试 |
| integration-reviewer | 集成审查 | 代码审查、跨模块集成、质量验收 |

## 3.1 Agent 协作原则

1. 由总控 Agent 负责统一调度。
2. 专业 Agent 只负责分配给自己的任务。
3. 独立任务可以并行执行。
4. 有依赖关系的任务必须等待前置节点完成。
5. 每个 Agent 必须提供执行报告。
6. 主控 Agent 必须检查实际变更和测试证据。
7. Agent 完成不代表整个工作流完成。

## 3.2 动态 Agent 选择

例如：

Java + Vue 项目：

- architect
- database
- java-backend
- web-frontend
- qa-engineer
- integration-reviewer

Python + React 项目：

- architect
- database（如有数据库工作）
- Web 前端
- 对应 Python 开发 Agent
- qa-engineer
- integration-reviewer

项目可以在配置中选择需要启用的 Agent。

未来新增技术栈时，可以增加专业 Agent，而不需要重写整个工作流核心。

---

# 第四章 工作流执行机制

## 4.1 工作流生命周期

一次任务的标准生命周期：

```text
任务输入
   |
   v
读取项目配置
   |
   v
读取任务信息
   |
   v
需求分析与技术设计
   |
   v
任务拆解，建立 DAG
   |
   v
专业 Agent 并行执行
   |
   v
代码与测试验证
   |
   v
集成审查
   |
   v
必要的构建检查
   |
   v
生成最终报告
   |
   v
工作流完成
```

实际节点根据项目配置、任务类型和依赖关系动态确定。

## 4.2 DAG 任务调度

DAG（Directed Acyclic Graph，有向无环图）用于表示任务之间的依赖关系。

例如：

```text
             需求分析
                |
           技术方案设计
                |
          +-----+-----+
          |           |
       数据库设计    后端开发
          |           |
          +-----+-----+
                |
             前端开发
                |
              QA
                |
           集成审查
                |
             完成
```

调度规则：

- 所有前置依赖满足后，节点进入 READY。
- READY 节点可以自动启动。
- 无依赖关系的节点允许并行。
- 某节点失败，只阻断依赖该节点的任务。
- 不相关节点继续执行。
- 主控 Agent 根据实际状态重新计算 DAG。

## 4.3 Workflow Continuation Protocol

这是平台的重要可靠性机制。

核心规则：

**子 Agent 完成不等于工作流完成。**

每次子 Agent 返回后，主控 Agent 必须：

1. 读取 Agent Report。
2. 校验报告内容和完成证据。
3. 检查代码修改、Git Commit 和 Worktree。
4. 检查测试结果。
5. 更新任务状态文件。
6. 重新计算 DAG。
7. 启动所有依赖已满足的节点。
8. 记录调度结果。

主控 Agent 不允许仅因为一个子 Agent 返回就结束整个会话。

## 4.4 完成判定

任务只有满足以下条件才可以标记为工作流 COMPLETED：

- 所有必需 DAG 节点完成。
- QA 已完成。
- 集成审查已完成。
- 必需的构建和测试已完成。
- Agent 报告和证据完整。
- 最终报告生成。
- 执行状态一致。

注意：

工作流 COMPLETED 不代表禅道任务已经关闭。

禅道任务的完成或关闭必须遵循单独的授权流程。

## 4.5 中断恢复

当 Claude Code、终端或 Agent 中断后，可以通过同一任务入口重新启动工作流。

恢复时应读取：

- `run-state.json`
- `tasks.yaml`
- `session.json`
- Agent Reports
- Git 状态
- Worktree 状态
- 审计记录

恢复原则：

- 从可信检查点继续。
- 不重复执行已经完成的开发节点。
- 不重复执行可能产生副作用的写操作。
- 对不确定的节点先核实实际状态。
- 不允许通过恢复机制绕过人工审批。

---

# 第五章 安装与环境配置

## 5.1 环境要求

当前已验证的主要环境：

| 软件 | 要求或版本 |
|---|---|
| 操作系统 | Windows 11 |
| Claude Code | 2.1.310（当前实测环境） |
| Python | 3.13.1 |
| Shell | Git Bash |
| Git | 可正常执行提交、分支和 Worktree 操作 |
| 通知服务 | cc-connect / 钉钉 |
| 外部系统 | 根据项目配置选择 |

不同团队可以根据公司环境调整版本，但升级 Claude Code、Python 或 cc-connect 后，应执行相应回归测试。

## 5.2 获取工作流仓库

```bash
git clone <公司内部工作流仓库地址> task-workflow
cd task-workflow
```

工作流仓库地址由公司平台维护人员提供。

## 5.3 安装个人级 Skill 和 Agent

执行：

```bash
bash scripts/install.sh
```

安装程序负责将工作流 Skill 和专业 Agent 安装到当前用户的 Claude Code 环境。

目标是实现：

- 任意业务项目目录都可以调用工作流。
- 不需要在每个项目重复复制 Skill。
- 工作流源文件统一在工作流仓库维护。
- 用户个人环境与业务项目相互隔离。

Windows 环境下如果软链接不可用，应使用安装脚本支持的复制或同步方式。

安装后重新启动 Claude Code，并确认 `/zentao-dev-workflow` 可以识别。

## 5.4 MCP 人工决策服务配置

使用 HITL 功能的人员需要配置 human-decision MCP Server。

当前用户级注册方式：

```bash
claude mcp add human-decision \
  --scope user \
  -- python <WORKFLOW_HOME>/agent-manager/human_decision/mcp_server.py
```

其中 `<WORKFLOW_HOME>` 必须替换为实际工作流仓库绝对路径。

注册后：

1. 重新启动 Claude Code。
2. 执行 `/mcp` 检查 MCP Server。
3. 确认 `human-decision` 已连接。
4. 使用工作流中的人工决策能力进行验证。

MCP 用户级配置保存在个人 Claude Code 配置中，不应将个人绝对路径和账号凭据直接提交到公共项目配置。

## 5.5 Windows 常驻服务

当前 cc-connect 已通过 Windows 用户级计划任务运行，避免依赖 CMD 窗口。

HITL daemon 当前使用：

- HKCU Run 登录自启动。
- 独立 supervisor 监督进程。
- daemon 异常退出后自动拉起。
- 运行日志记录。

当前实现的限制：

HKCU Run 方案是在用户登录时启动，并不等同于系统启动时、用户未登录情况下运行的 Windows 服务。

真实机器重启后的完整生效性仍需进一步验收。

---

# 第六章 人员和项目配置

## 6.1 配置分层

平台将配置分为四类：

| 配置文件 | 用途 |
|---|---|
| `config/workflow.yaml` | 全局工作流策略 |
| `config/users/{id}.yaml` | 当前人员的身份和个人配置 |
| `config/projects/{key}.yaml` | 项目路径、技术栈、Agent 和构建配置 |
| `config/adapters/*.yaml` | 外部工具适配器配置 |

配置由 `scripts/_config.py` 统一加载。

当前配置加载器支持六层配置加载机制，具体优先级以仓库实现和配置参考文档为准。

## 6.2 人员配置

每位使用者应使用自己的身份配置。

例如：

```text
config/users/
    developer_a.yaml
    developer_b.yaml
```

人员配置主要用于：

- 识别当前使用者。
- 配置个人工具身份。
- 关联个人账号。
- 指定个人工作流选项。
- 隔离不同人员的本地配置。

真实人员配置属于个人或受控环境数据，不应提交到公共 Git 仓库。

## 6.3 项目配置

每个项目使用独立配置：

```text
config/projects/
    jeebootx.yaml
    demo-react.yaml
```

项目配置负责描述：

- 项目标识。
- 项目根目录。
- 技术栈。
- 关联仓库。
- 启用的 Agent。
- 构建和测试方式。
- 外部工具集成。
- 项目特定约束。

添加新项目时，应先建立项目配置，再执行配置校验。推荐使用项目注册功能自动完成，
见 6.6「项目注册与自动发现」。

项目配置与个人路径分离：

- 项目公共配置只描述仓库清单（`key` / `role` / `technology` / `remote_url`）和禅道归属
  （`zentao.project_id`、`zentao.product_ids`），可以提交公共 Git 仓库。
- 个人本地仓库路径写入 `config/users/{id}.yaml` 的 `project_paths`，同一项目不同人员
  可以使用不同本地路径，个人路径不进入 Git。
- 兼容旧式 `repositories[].path: "${ENV_VAR}"` 写法。

不要在 Skill 或 Python 脚本中硬编码某个业务项目的本机绝对路径。

## 6.4 外部工具适配器

平台将工具与工作流核心解耦。

| 适配器 | 主要用途 | 是否必须 |
|---|---|---|
| ZenTao | 读取任务、查询状态、授权范围内的进度写回 | 否 |
| Jenkins | 构建、测试、获取执行结果和日志 | 否 |
| Notification | 钉钉等消息通知和人工确认 | 按功能需要 |

无禅道的项目可以使用其他任务来源或直接提供任务描述。

无 Jenkins 的项目可以根据项目配置执行本地构建和测试命令。

不要求所有项目都安装相同工具。

## 6.5 已验证的通用性

当前已有两个不同技术栈项目的实测结果：

| 项目 | 技术栈 | 仓库数量 | 启用 Agent | 外部适配器 |
|---|---|---:|---:|---|
| jeebootx | Java + Vue + uni-app | 4 | 7 | ZenTao、Jenkins、钉钉 |
| demo-react | Python + React | 2 | 5 | none |

两个项目均通过配置校验，执行状态相互隔离。

这证明工作流核心不依赖某个固定业务项目，也不强制依赖禅道或 Jenkins。

## 6.6 项目注册与自动发现

平台提供标准化的新项目接入入口：

```text
/workflow-register-project
```

注册流程（自动校验，配置写入前必须人工确认）：

1. 查询当前用户可访问的禅道项目并选择要接入的项目。
2. 确认项目标识 `project_key`（自动查重，已存在则拒绝重建）。
3. 配置本地仓库路径（支持一个项目关联多个 Git 仓库）。
4. 自动识别技术栈（Maven / Gradle / Vue / React / uni-app / Python）。
5. Git 只读校验（路径、仓库特征、根目录、remote、工作区状态）。
6. 生成注册计划并展示（含确认指纹），用户确认后原子写入配置。
7. 输出注册报告。

注册只写两处配置：`config/projects/{key}.yaml`（项目公共配置）与
`config/users/{id}.yaml`（追加 `project_paths` 个人路径映射）。
不覆盖既有配置、不写禅道、不 clone / checkout、不修改 Git remote；校验失败不写入。

任务到项目的自动发现规则（日常使用见 7.1）：

- 只给出任务号时，平台查询任务归属并按可靠性匹配：项目 ID 精确匹配 > 产品 ID 辅助匹配 >
  显式映射 > 名称辅助识别。名称命中不能单独作为可靠依据，必须人工确认。
- 多个候选或无法唯一确定时安全阻断并询问使用者，不猜测项目。
- 未注册的项目提示先执行注册，不创建执行目录。

详细说明见 `docs/project-registry.md`。

---

# 第七章 日常使用说明

## 7.1 基本使用方式

进入任意已配置项目的根目录：

```bash
cd /path/to/your/project
claude
```

在 Claude Code 中执行：

```text
/zentao-dev-workflow {project_key} {task_id}
```

例如：

```text
/zentao-dev-workflow jeebootx 3413
```

另一个项目：

```text
/zentao-dev-workflow demo-react 1001
```

其中：

- `project_key`：对应 `config/projects/` 中的项目标识。
- `task_id`：任务系统中的任务编号或工作流约定的任务标识。

也可以只给任务号，由平台自动识别所属项目：

```text
/zentao-dev-workflow #5001
```

平台查询任务归属并匹配项目注册表：唯一确定时直接执行；仅名称相似或多候选时
询问使用者确认；未注册时提示先执行 `/workflow-register-project`，不猜测项目。

具体参数要求以当前 Skill 的 `SKILL.md` 为准。

## 7.2 标准操作流程

### 第一步：确认项目

检查：

- 项目配置是否存在。
- 项目根目录是否正确。
- 技术栈和 Agent 配置是否匹配。
- Git 工作区是否存在未提交改动。
- 是否有其他会话正在处理同一任务。

### 第二步：读取任务

如果配置了禅道，读取指定任务的：

- 标题。
- 任务描述。
- 验收标准。
- 当前状态。
- 相关任务信息。

如果没有禅道，则通过工作流支持的任务输入方式提供需求。

### 第三步：需求分析

Architect Agent 分析：

- 业务目标。
- 技术影响范围。
- 相关模块。
- 数据库变化。
- 前后端改动。
- 测试要求。
- 潜在风险。

### 第四步：建立任务 DAG

主控 Agent 将任务拆解成可执行节点，并识别依赖关系。

### 第五步：Agent 开发

根据项目技术栈启动专业 Agent。

允许独立节点并行，避免多个 Agent 无协调地修改同一文件或同一模块。

### 第六步：测试与审查

QA Agent 执行测试，Integration Reviewer 负责跨模块检查。

### 第七步：构建检查

如果项目配置了 Jenkins，则可以调用 Jenkins 适配器进行构建检查。

如果没有 Jenkins，则按照项目配置执行本地构建和测试。

### 第八步：生成报告

工作流生成任务执行报告，记录：

- 需求和实施内容。
- Agent 执行情况。
- 修改文件。
- Git Commit。
- 测试结果。
- 构建结果。
- 遗留问题。
- 后续建议。

---

# 第八章 HITL 人工决策机制

## 8.1 功能定位

HITL（Human-in-the-Loop）是平台的人工决策闭环。

当 Agent 执行过程中遇到需要人工确认的操作，不应擅自继续，而是发起人工决策请求。

系统通过通知渠道向指定决策人发送请求，等待合法回复后再恢复原任务。

## 8.2 核心模块

当前实现位于：

```text
agent-manager/human_decision/
```

主要能力包括：

| 模块 | 说明 |
|---|---|
| Decision Manager | 决策请求生命周期管理 |
| Failure Detector | 异常分类与失败检测 |
| SQLite Store | 决策数据持久化 |
| Notifier | 钉钉及 cc-connect 通知 |
| Identity Allowlist | 决策人身份白名单 |
| Idempotency | 防止重复回复和重复处理 |
| Session Recovery | Agent 会话恢复 |
| Timeout Recovery | 超时检测与恢复 |
| MCP Server | 为 Claude Code 提供人工决策工具 |
| CLI | 查询等待中的决策和失败信息 |

## 8.3 决策流程

```text
Agent 执行任务
      |
      v
发现需要人工决策
      |
      v
生成 Decision
      |
      v
持久化决策状态
      |
      v
发送钉钉通知
      |
      v
Agent 进入 WAITING_HUMAN
      |
      v
等待决策人回复
      |
      v
验证决策人身份
      |
      v
校验回复及决策状态
      |
      v
执行恢复
      |
      v
Agent 继续原任务
```

## 8.4 决策人白名单

决策人白名单使用本地配置：

```text
config/adapters/hitl.local.yaml
```

该文件属于本地私有配置，必须保持 Git 忽略。

人员身份不能仅凭消息内容判断，必须使用可信的用户身份标识。

当前设计采用 fail-closed 原则：

- 未配置决策人：拒绝授权。
- 未知决策人：拒绝授权。
- 身份校验失败：拒绝授权。
- 合法决策人：根据请求状态和权限处理。

每位公司成员应配置自己的决策人身份，不能直接复制其他人的私有身份配置。

## 8.5 幂等处理

决策回复使用唯一约束：

```text
UNIQUE(decision_id, msg_id)
```

配合 `INSERT OR IGNORE` 防止并发或重复消息导致同一决策被处理多次。

## 8.6 人工决策状态

主要状态包括：

- 等待决策。
- 等待人工（WAITING_HUMAN）。
- 已批准。
- 已拒绝。
- 已超时。
- 执行失败。

实际状态枚举以当前代码为准。

## 8.7 异常处理

当前 Failure Detector 已覆盖多类异常，包括：

- Agent 执行失败。
- 工具调用失败。
- 会话异常。
- 超时。
- 通知异常。
- 恢复异常。

一般失败可以在策略允许的范围内重试。

需要人工授权的高风险操作不得通过重试绕过审批。

## 8.8 会话恢复

当前恢复能力包括多级恢复策略：

- 优先尝试恢复原有会话。
- 根据可用状态尝试其他恢复路径。
- 必要时基于持久化检查点重建任务上下文。

已完成独立隔离环境中的真实破坏性测试：

1. 创建独立测试会话。
2. 保存上下文标记 `ALPHA-77`。
3. 强制终止测试 Agent 进程。
4. 保留原有 `agent_session_id`。
5. 触发 `claude --resume`。
6. 验证恢复日志 `is_resume=true`。
7. 再次验证上下文标记仍为 `ALPHA-77`。

正式 cc-connect 会话全程未受影响。

---

# 第九章 自动化脚本说明

| 脚本 | 作用 |
|---|---|
| `scripts/_config.py` | 统一加载配置 |
| `scripts/zt.py` | 禅道任务查询、状态读取和授权范围内的写回 |
| `scripts/jenkins_run.py` | Jenkins Job 检查、构建触发、轮询和结果收集 |
| `scripts/notify.sh` | 通知和人工确认 |
| `scripts/audit.py` | 执行状态、报告、文件变更和审计 |
| `scripts/install.sh` | 安装和卸载个人级 Skill、Agent |

## 9.1 Jenkins 使用边界

Jenkins 适配器可以检查 Job、触发构建、轮询执行状态和获取构建日志。

在触发 Job 前，必须确认：

- Job 的实际用途。
- 是否仅执行构建和测试。
- 是否包含部署步骤。
- 是否会重启业务服务。
- 是否存在其他生产环境副作用。

不能因为 Job 名称包含 build 就假设它只做构建。

未经明确授权，不执行部署和重启操作。

## 9.2 禅道使用边界

平台支持禅道任务读取和进度管理。

禅道状态写回必须遵循当前用户的授权规则。

平台不得自动执行：

- `task_finish`
- `task_close`

工作流执行完成和禅道任务完成是两个不同概念。

---

# 第十章 任务状态、报告与审计

## 10.1 状态隔离

每个项目、每个任务都有独立执行目录：

```text
execution/{project_key}/{task_id}/
```

例如：

```text
execution/
├── jeebootx/
│   └── 3413/
│       ├── run-state.json
│       ├── tasks.yaml
│       ├── session.json
│       ├── reports/
│       └── audit.jsonl
│
└── demo-react/
    └── 1001/
        ├── run-state.json
        ├── tasks.yaml
        ├── session.json
        ├── reports/
        └── audit.jsonl
```

实际文件以任务初始化和当前模板为准。

## 10.2 主要状态文件

| 文件 | 主要用途 |
|---|---|
| run-state.json | 工作流整体状态 |
| tasks.yaml | DAG 节点及依赖 |
| session.json | 会话及恢复信息 |
| reports/ | Agent 执行报告 |
| audit.jsonl | 执行审计记录 |

## 10.3 Agent Report

每个 Agent 应提供结构化报告，至少说明：

- 任务目标。
- 实际执行内容。
- 修改文件。
- 测试命令和结果。
- Git Commit（如有）。
- 未解决问题。
- 阻塞原因。
- 后续建议。

报告必须与实际代码和测试证据相互印证。

## 10.4 审计记录

审计数据用于回答：

- 谁执行了什么任务？
- 哪个 Agent 修改了哪些文件？
- 任务何时开始、何时完成？
- 是否发生失败和重试？
- 是否触发人工审批？
- 审批结果是什么？
- 是否存在未解决问题？

测试环境必须与正式任务审计隔离，避免测试数据污染真实 execution 记录。

---

# 第十一章 安全与权限规范

## 11.1 凭据管理

以下内容不得提交到 Git：

- 禅道账号和密码。
- Jenkins Token。
- 钉钉凭据。
- API Key。
- 用户身份白名单。
- 本地 HITL 配置。
- 私有连接信息。

凭据应放在本地配置或安全的凭据管理系统中。

提交前应检查：

```bash
git status
git diff --cached
```

确认没有真实凭据、日志泄漏或个人配置进入暂存区。

## 11.2 多用户隔离

不同研发人员应分别使用：

- 自己的 Claude Code 用户环境。
- 自己的人员配置。
- 自己的 MCP 用户级配置。
- 自己的决策人白名单。
- 自己授权的外部工具账号。

不得通过复制配置的方式共享其他人的 Token 或身份信息。

## 11.3 高风险操作

高风险操作必须经过明确授权或 HITL 决策。

包括但不限于：

- 生产环境部署。
- 业务服务重启。
- 数据删除或不可逆修改。
- 生产数据库操作。
- 超出当前任务授权范围的外部系统写操作。

人工审批通过也不意味着可以扩大原始任务的授权范围。

## 11.4 Git 安全

- 修改前检查工作区。
- 不覆盖其他会话的未提交文件。
- 不擅自删除其他 Agent 的在途成果。
- 不将无关文件混入当前 Commit。
- 提交后检查 Commit 内容。
- 不自动推送远程，除非得到明确授权。

---

# 第十二章 已有实施与验收结果

## 12.1 通用化框架

实施范围：P01–P10。

Git Commit：

```text
8d11874
```

交付内容：

- 通用总控 Skill。
- 七个专业 Subagents。
- 配置加载器。
- 四类工具适配脚本。
- 个人级安装与卸载机制。
- 项目和人员配置分层。
- 独立任务状态目录。
- 双项目通用性验证。

17 项验收标准全部通过。

## 12.2 HITL 实施

Git Commit：

```text
f50da7e
```

该提交完成了 HITL 与 Agent Execution Manager 的一轮稳定性加固。

随后完成剩余两项必做工作：

```text
bbee7e3
```

最终验收报告：

```text
execution/hitl/ACCEPTANCE-REPORT.md
```

## 12.3 测试结果

最新补充验收记录：

| 测试模块 | 结果 |
|---|---:|
| human_decision | 51 passed |
| agent-manager | 20 passed |
| 合计 | 71 passed |

两个测试模块分别在正确目录运行，避免从仓库根目录合并收集造成的 Python import 冲突。

## 12.4 关键实测结果

| 项目 | 结果 |
|---|---|
| MCP 用户级注册 | 已完成 |
| HITL 决策人白名单 | 已完成并通过冒烟验证 |
| daemon 异常恢复 | 已通过真实杀进程测试 |
| cc-connect 用户级运行 | 已通过计划任务运行验证 |
| Resume 破坏性隔离测试 | 已通过 |
| 正式会话保护 | 已验证 |
| 审计测试数据污染修复 | 已提交 |
| 凭据入库检查 | 通过 |

## 12.5 项目注册与自动发现

已交付（2026-11-17，验收 15/15 通过）：

- `/workflow-register-project` 项目注册 Skill 与注册 CLI（计划 / 确认 / 原子写入）。
- 任务号自动识别与统一项目解析（`scripts/project_resolver.py`）。
- 仓库识别与 Git 校验（`scripts/repo_check.py`）。
- 用户级 `project_paths` 多仓库路径映射（多用户不同路径）。
- 新增 58 项自动化测试；测试基线 177 项全部通过。
- jeebootx / demo-react 兼容性验证通过。

实施与验收详情见 `reports/PROJECT-REGISTRY-IMPLEMENTATION.md` 与
`reports/PROJECT-REGISTRY-ACCEPTANCE.md`。

## 12.6 当前遗留问题

以下项目不得在内部推广时描述为已经完全解决：

### A. HITL daemon 启动级别

由于当前 Windows UAC 权限限制，未能创建预期的当前用户计划任务版本。

采用 HKCU Run + supervisor 作为替代方案。

已验证：

- 用户登录自启动链路。
- 关闭终端后继续运行。
- daemon 异常退出后自动拉起。

尚未验证：

- 真实机器重启后的完整恢复。
- 用户未登录时运行。

### B. cc-connect v1.5.0 send

已发现 send 可能出现返回成功但消息实际未投递的问题。

需要升级后通过真实钉钉消息投递进行回归验证。

### C. Windows 进程存活探测

已发现 Windows 环境下 `os.kill(pid, 0)` 的行为风险，相关实现已固化禁用说明。

后续修改进程探测逻辑时，必须使用经过验证的 Windows 兼容方式。

### D. 项目隔离和辅助脚本

部分历史设计文档仍位于 `docs/3413/`，尚未完成通用项目目录隔离。

`start-claude.sh` 仍存在路径硬编码，后续可以进一步配置化。

---

# 第十三章 常见问题与故障排查

## 13.1 找不到 `/zentao-dev-workflow`

检查：

1. 是否执行 `scripts/install.sh`。
2. 是否安装到了当前用户的 Claude Code Skill 目录。
3. 是否重新启动 Claude Code。
4. 是否存在同名 Skill 冲突。
5. 是否正确安装了专业 Agent。

## 13.2 项目配置不存在

检查：

- `project_key` 是否正确。
- `config/projects/{project_key}.yaml` 是否存在。
- 项目根目录是否正确。
- 当前用户是否有读取权限。

## 13.3 禅道无法读取任务

检查：

- 当前人员配置。
- 禅道适配器配置。
- 账号是否有效。
- 当前用户是否有任务读取权限。
- 网络是否可以访问禅道服务。

不要将其他人的账号或 Token 作为临时解决办法。

## 13.4 Jenkins 构建失败

先确认：

- Jenkins 是否可访问。
- Job 是否存在。
- Jenkins 凭据是否有效。
- Job 是否具有构建权限。
- 构建日志中的实际错误。

区分网络、权限、构建脚本和代码问题。

## 13.5 钉钉没有收到通知

不能只看 send 命令的返回码。

应检查：

- cc-connect 进程是否存活。
- 通知服务日志。
- 实际消息投递结果。
- 目标会话是否正确。
- 决策人身份配置是否正确。

当前 cc-connect v1.5.0 的 send 虚报问题仍待升级回归。

## 13.6 Agent 执行中断

重新调用同一任务：

```text
/zentao-dev-workflow {project_key} {task_id}
```

由工作流检查原有状态和 Git 变更后恢复。

不得直接删除执行目录或清空状态文件。

## 13.7 Agent 一直等待人工决策

检查：

- 决策是否已经发送。
- 决策人是否在白名单中。
- 回复消息是否被正确识别。
- 决策状态是否已经持久化。
- cc-connect 是否正常。
- HITL daemon 是否运行。

未经确认，不要直接修改 SQLite 数据库中的决策状态来解除阻塞。

## 13.8 项目无法自动识别

检查：

- 项目是否已注册（`config/projects/` 是否存在对应配置）。
- 项目配置的禅道归属（`zentao.project_id`）是否与任务所属项目一致。
- 是否出现多个候选项目（需要显式指定 `project_key`）。
- 是否仅名称相似（名称不能单独作为可靠依据，需人工确认）。

未注册项目应先执行 `/workflow-register-project` 接入。平台不猜测项目目录，
识别失败时不会创建执行目录。

## 13.9 项目注册失败

检查：

- `project_key` 是否已存在。
- 禅道项目是否已注册到其他 `project_key`（不允许多对一映射）。
- 仓库路径是否存在且为 Git 仓库。
- 注册指纹是否与计划一致（计划变更后需重新确认）。
- 用户路径映射是否与已有配置冲突（平台拒绝覆盖已有映射）。

注册失败不会留下不完整配置；修正后重新执行注册计划即可。

---

# 第十四章 公司内部推广与运维建议

## 14.1 研发人员使用规范

普通研发人员只需要完成：

1. 获取工作流仓库。
2. 安装 Skill 和 Agent。
3. 配置个人身份。
4. 配置需要使用的外部工具。
5. 注册项目（`/workflow-register-project`）或手工建立项目配置。
6. 从业务项目目录启动 Claude Code。
7. 使用统一入口执行任务。

不要求每个研发人员理解 DAG、HITL 或内部 Python 实现。

## 14.2 项目接入规范

新增项目时：

1. 执行 `/workflow-register-project` 完成注册（自动查重、技术栈识别、Git 校验）。
2. 确认项目公共配置与个人路径映射（写入前须人工确认）。
3. 选择启用的 Agent。
4. 按需接入禅道、Jenkins 和通知系统。
5. 进行配置校验。
6. 选取一个非生产高风险任务进行端到端试运行。
7. 验证任务状态隔离、报告和恢复能力。

## 14.3 平台维护人员职责

平台维护人员负责：

- 维护工作流核心。
- 管理 Agent 模板。
- 维护工具适配器。
- 管理配置模板。
- 维护安装和升级机制。
- 执行回归测试。
- 检查审计和凭据安全。
- 维护 HITL 服务。
- 处理系统级故障。

## 14.4 版本升级规范

每次升级应：

1. 检查代码变更。
2. 检查配置兼容性。
3. 检查 Skill 和 Agent 是否有破坏性变更。
4. 执行 human_decision 测试。
5. 执行 agent-manager 测试。
6. 执行双项目配置校验。
7. 执行关键功能回归。
8. 更新版本和验收报告。

不建议未经验证直接在全公司所有研发人员环境中批量更新。

## 14.5 推荐推广路径

| 阶段 | 范围 | 目标 |
|---|---|---|
| 第一阶段 | 平台维护人员 | 验证安装、配置和故障恢复 |
| 第二阶段 | 小范围研发试点 | 验证真实项目研发流程 |
| 第三阶段 | 多技术栈项目 | 验证跨项目通用性 |
| 第四阶段 | 部门级推广 | 统一使用规范和项目接入流程 |
| 第五阶段 | 持续运营 | 监控质量、失败率、耗时和成本 |

---

# 第十五章 后续建设方向

以下属于后续规划，不代表已经交付。

1. **企业级统一配置管理**：支持集中管理人员、项目和工具配置。
2. **凭据管理集成**：接入公司统一 Secret 管理服务。
3. **工作流可视化**：展示 DAG、Agent 状态、失败原因和人工审批进度。
4. **统一运行监控**：统计任务成功率、失败率、重试次数和平均耗时。
5. **Agent 执行成本分析**：统计 Token、执行时间和并行效率。
6. **更多研发工具适配**：根据公司现有工具增加适配器。
7. **企业级部署和运维**：进一步完善 daemon 生命周期管理和服务监控。
8. **质量度量**：建立研发效率、缺陷率、测试覆盖和交付质量指标。

---

# 附录 A：快速使用清单

## 首次安装

- [ ] 已安装 Claude Code。
- [ ] 已安装 Python 3.13。
- [ ] 已获取工作流仓库。
- [ ] 已执行 `bash scripts/install.sh`。
- [ ] 已确认 `/zentao-dev-workflow` 可用。
- [ ] 已配置个人身份。
- [ ] 已创建项目配置（或已执行 `/workflow-register-project` 完成注册）。
- [ ] 已完成配置校验。
- [ ] 按需配置 MCP 和通知系统。

## 执行任务

- [ ] 确认项目标识。
- [ ] 确认任务编号。
- [ ] 检查 Git 工作区。
- [ ] 确认没有其他会话冲突。
- [ ] 调用工作流入口。
- [ ] 检查 Agent 执行报告。
- [ ] 检查 QA 和集成审查。
- [ ] 检查构建结果。
- [ ] 检查最终报告。
- [ ] 确认没有未经授权的外部操作。

## 发生异常

- [ ] 检查 run-state.json。
- [ ] 检查 tasks.yaml。
- [ ] 检查 session.json。
- [ ] 检查 Agent Reports。
- [ ] 检查 Git 和 Worktree。
- [ ] 检查审计记录。
- [ ] 确认是否需要人工决策。
- [ ] 从可信检查点恢复。

---

# 附录 B：关键路径

| 资源 | 路径 |
|---|---|
| 工作流仓库 | `D:\WorkSpace\task-workflow` |
| 总控 Skill | `.claude/skills/zentao-dev-workflow/SKILL.md` |
| Agent 定义 | `.claude/agents/` |
| 全局配置 | `config/workflow.yaml` |
| 人员配置 | `config/users/` |
| 项目配置 | `config/projects/` |
| 工具配置 | `config/adapters/` |
| 配置加载器 | `scripts/_config.py` |
| HITL 模块 | `agent-manager/human_decision/` |
| 执行状态 | `execution/{project_key}/{task_id}/` |
| HITL 验收报告 | `execution/hitl/ACCEPTANCE-REPORT.md` |

---

# 附录 C：关键 Git 版本

| 提交 | 说明 |
|---|---|
| `8d11874` | 通用化工作流框架 P01–P10 完成 |
| `f50da7e` | HITL 与 Agent Execution Manager 稳定性加固 |
| `bbee7e3` | HITL 剩余必做项验收报告及相关修复 |

---

**文档结束**

本手册描述的是截至 2026-11-17 已实施和已验证的能力。平台后续版本应同步更新本手册、配置示例和验收记录。