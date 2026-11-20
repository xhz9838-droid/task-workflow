# zentao-dev-workflow（通用多 Agent 研发工作流）

> 通用研发工作流核心，不含任何项目/人员/凭据。各项目接入见下方"接入新项目"。
> 来源：编排仓库通用核心，经只读审计 + P0 路径去硬编码后同步（2026-11-17）。

## 这是什么

一个通用多 Agent 研发工作流总控：按项目配置加载仓库/技术栈/Agent/工具适配器，执行
需求分析→设计→DAG 调度→开发→测试→集成审查→人工审批→任务回写的完整流程。

核心特性：
- **不写死**项目名、人员账号、机器路径、Jenkins Job、任务 ID
- **DAG 节点状态唯一真相源** = agent-manager SQLite（`node_dispatches` 表）；
  `run-state.json` 降为只读导出快照
- **派发协议**：`register-dispatch` → 主控调真实 Agent 工具 → `confirm-running` → `record-result`
- **L1/L2/L3 风险分级**，L3 人工审批不绕过
- 可无 ZenTao/Jenkins 独立运行（只做需求分析/开发/测试/审查/状态管理）

## 目录结构

```
zentao-dev-workflow/
├── .claude/skills/     # 总控 Skill + 项目注册 Skill（SKILL.md + references + templates）
├── .claude/agents/     # 7 个专业 Subagents（dw-*.md）
├── scripts/            # 工具适配器 + 配置加载器 + dispatch.py + doctor.py + install.sh
├── agent-manager/      # 状态管理器（SQLite）+ runner/monitor/retry/verifier + HITL
├── config/             # 配置模板（.example.yaml）+ workflow.yaml
├── tests/              # 编排层测试
├── VERSION             # 产品版本
├── CLAUDE.md           # 编排协议根规则（8 条硬规则）
└── .env.example        # 机器级凭据模板
```

> 发行仓库可能使用顶层 `skill/` + `agents/` 布局；`install.sh` 会自动识别两种布局。

## 安装到个人级

### 方式 1：用本目录的 install.sh（推荐）

```bash
bash scripts/install.sh              # 安装 Skill（含注册 Skill）+ Agents + 安装记录 + 用户级 workflow_home
bash scripts/install.sh --with-mcp   # 额外注册 HITL MCP（user scope，任意项目目录可用）
bash scripts/install.sh --link       # 软链（改源码即时生效）
bash scripts/install.sh --uninstall  # 卸载（保留 config/execution/.env）
```

安装到 `~/.claude/skills/{zentao-dev-workflow,workflow-register-project}/`、
`~/.claude/agents/dw-*.md`，并写 `~/.claude/zentao-dev-workflow.home` 与
`~/.claude/zentao-dev-workflow.json`（`workflow_home`，保留已有字段）。
**不会**覆盖 `config/`、`execution/`、`.env` 与 SQLite 数据。

### 方式 2：lianzhu-skills 全局安装脚本（发行仓库）

```bash
bash install-global.sh --only zentao-dev-workflow   # 在 lianzhu-skills 仓库根执行
```

> **工作流根定位**：Skill 安装目录只含 SKILL.md / references / templates，**不含** `scripts/`、
> `config/`、`execution/`、`.env`、SQLite。启动顺序：
> ① `cat ~/.claude/zentao-dev-workflow.home` → ② `WORKFLOW_HOME` →
> ③ `~/.claude/zentao-dev-workflow.json:workflow_home` → ④ 工作流仓库内 `scripts/_home.py`。
> 拿到候选后复核 `python -I "{WF}/scripts/_home.py"`；全落空则明确报错，不猜测。
> 诊断：`python -I "{WF}/scripts/doctor.py" [--project <key>] [--user <id>]`。

## 接入新项目

两种注册方式（plan→确认→apply，两段式，不重复实现注册逻辑）：

- **手动注册**：`/workflow-register-project` 或 `scripts/project_register.py plan/apply`
  ——用户给齐 project_key/name/repos，不依赖禅道，适合离线或凭据未配。
- **任务驱动注册**：由主控从禅道任务提取 `project`/`projectName`/`product_ids`，
  再调用 `project_register.py plan/apply`（当前仓库未提供独立脚本）。
  工作流启动时若项目未注册，主控就地走注册引导后继续，**不要求用户重启命令**。

前置：复制 `.env.example` → `.env` 填机器级凭据（路径/Jenkins/ZenTao）；
运行 `scripts/_config.py validate {key} {user_id}` 校验（用户 `project_paths` 优先）。

接入后任意目录启动 Claude Code：`/zentao-dev-workflow {project_key} {task_id}`

## 安全约束

- **不进 git**：`.env`、`config/users/*.yaml`（非 example）、`config/projects/*.yaml`（非 example）、
  `execution/`、`agent-manager/logs/*.db`
- 凭据只放 `.env`（gitignored）或用户级工具配置
- 不自动部署、不自动重启
- task_finish 经 Verifier 门禁后自动（须读回确认）；task_close 关闭条件满足后自动（须读回确认，
  不满足则暂缓并记录原因）

## 关键文档

| 场景 | 文件 |
|---|---|
| 总控流程 | `.claude/skills/zentao-dev-workflow/SKILL.md` |
| 8 条硬规则 | `CLAUDE.md` |
| 派发协议（SQLite 唯一真相源） | `.claude/skills/zentao-dev-workflow/references/continuation-protocol.md` |
| 中断恢复、僵尸 RUNNING 检测 | `.claude/skills/zentao-dev-workflow/references/recovery-protocol.md` |
| L1/L2/L3 审批 | `.claude/skills/zentao-dev-workflow/references/approval-policy.md` |
| Agent 调度 | `.claude/skills/zentao-dev-workflow/references/agent-dispatch.md` |
| 项目适配 | `.claude/skills/zentao-dev-workflow/references/project-adaptation.md` |

## 运行诊断与门禁

```bash
python -I scripts/doctor.py [--project <key>] [--user <id>] [--json]   # 版本/根/配置/依赖/DB/安装
python -I scripts/dispatch.py --project <k> --task-id <id> gate        # 结束门禁（ok 才可 COMPLETED）
python -I scripts/dispatch.py --project <k> --task-id <id> flush-writes # 重试禅道回写队列
```

## 测试

```bash
bash scripts/run_tests.sh          # 全部测试（编排层 + agent-manager + HITL，一次运行）
python -I -m pytest -q             # 等价（pytest.ini 已声明 testpaths）
```

## 与 zentao-* skill 族的关系

本 skill 复用 `zentao/_shared/` 的禅道客户端（task_source 适配器）、Jenkins、钉钉通知。
无 ZenTao 配置时仍可独立运行（需求分析/开发/测试/审查/状态管理）。
