# P01 现状盘点

> 只读盘点 · 2026-11-16 · 未修改任何文件

## 一、工作流仓库结构现状

```text
D:\WorkSpace\task-workflow\
├── CLAUDE.md                      # 含项目硬编码
├── Jenkinsfile.ai-test            # 通用测试流水线（无硬编码）
├── .gitignore                     # 已保护 .env / config.json / .cc-connect / worktrees
├── .env                           # JENKINS_URL / JENKINS_USER / JENKINS_TOKEN（未入库 ✓）
├── .claude/
│   └── agents/                    # 7 个 Agent（角色通用，但含任务 ID 硬编码）
│       ├── architect.md
│       ├── database.md
│       ├── integration-reviewer.md
│       ├── java-backend.md
│       ├── mobile-app.md
│       ├── qa-engineer.md
│       └── web-frontend.md
├── scripts/
│   ├── zt.py                      # ZenTao 适配器（读 skill 级配置 ✓）
│   ├── jenkins_run.py             # Jenkins 适配器（WHITELIST 硬编码 ✗）
│   ├── notify.sh                  # 通知适配器（读 session.json ✓）
│   ├── audit.py                   # 审计（通用 ✓）
│   ├── start-claude.sh            # 启动器（路径硬编码 ✗）
│   └── jenkins_run.py_a           # 用户备份副本
├── execution/
│   └── 3413/                      # ⚠ 扁平结构，缺 project_key 层
│       ├── run-state.json
│       ├── session.json
│       ├── audit.jsonl
│       └── agent-reports/web-frontend-1.json
└── docs/
    ├── 3413/                      # #3413 设计文档（9 个文件）
    └── architecture/, execution/  # 早期环境调查文档
```

**缺失目录**：`.claude/skills/`（总控 Skill）、`config/`（配置层）、`.env.example`、`execution/upgrade/`

## 二、硬编码清单（需迁移至配置）

| # | 位置 | 硬编码内容 | 类别 | 迁移目标 |
|---|---|---|---|---|
| 1 | `CLAUDE.md:14-17` | 4 个 jeebootx 仓库绝对路径 | 项目 | `config/projects/jeebootx.yaml` |
| 2 | `CLAUDE.md:19` | worktree 路径 `D:/WorkSpace/.worktrees/<代号>-zt<id>` | 机器/项目 | `config/workflow.yaml`（worktree_root） |
| 3 | `.claude/agents/*.md:24` | commit 格式 `feat(3413)` | 任务 | 参数化 `feat(<TASK_ID>)` |
| 4 | `.claude/agents/*.md:11` | `execution/<id>/` 路径 | 项目 | `execution/<project_key>/<task_id>/` |
| 5 | `scripts/jenkins_run.py:73-76` | `WHITELIST = {ct-jeebootx-sanitation, jeebootx-ui}` | 项目 | `config/projects/*.yaml → integrations.jenkins.jobs` |
| 6 | `scripts/start-claude.sh:4` | `WORKFLOW_ROOT="/d/WorkSpace/task-workflow"` | 机器 | 脚本自定位（`dirname $0`） |
| 7 | `scripts/start-claude.sh:7-10` | 4 个仓库路径 | 项目 | `config/projects/*.yaml → repositories` |
| 8 | `execution/3413/session.json` | `build_url_template` 含 Jenkins URL | 项目 | 由适配器配置生成 |
| 9 | `execution/3413/` | 目录缺 project_key 层 | 项目 | `execution/{project_key}/{task_id}/` |
| 10 | `docs/3413/` | 设计文档无项目隔离 | 项目 | 迁移或保留（非阻塞） |

## 三、可复用能力清单

| 资产 | 通用度 | 说明 |
|---|---|---|
| 7 个 Subagents | 高 | 角色定义通用，仅 commit 格式与路径需参数化 |
| `scripts/zt.py` | 高 | ZenTao 适配器，读 `~/.claude/skills/zentao/_shared/config.json`（用户级 ✓） |
| `scripts/jenkins_run.py` | 中 | Jenkins 适配器，REST 客户端通用，仅白名单需配置化 |
| `scripts/notify.sh` | 高 | 通知适配器，读 `session.json`，无硬编码 ✓ |
| `scripts/audit.py` | 高 | 审计，`ROOT` 自定位，通用 ✓ |
| `Jenkinsfile.ai-test` | 高 | 参数化流水线，无硬编码 ✓ |
| ZenTao Skill | 高 | 用户级配置已隔离 ✓ |
| CC Connect | 高 | `~/.cc-connect/config.toml` 用户级 ✓ |
| `.gitignore` | 高 | 已保护 `.env` / `config.json` / `.cc-connect` ✓ |
| `execution/*/agent-reports/*.json` 报告格式 | 高 | 可直接模板化 |

## 四、当前配置来源

| 工具 | 配置位置 | 归属 | 状态 |
|---|---|---|---|
| ZenTao | `~/.claude/skills/zentao/_shared/config.json` | 用户级 | ✓ 已隔离 |
| Jenkins | `{WORKFLOW_HOME}/.env` | 机器级 | ✓ gitignored，缺 `.env.example` |
| CC Connect / DingTalk | `~/.cc-connect/config.toml` | 用户级 | ✓ 已隔离 |
| Jenkins Job 白名单 | `scripts/jenkins_run.py` 硬编码 | ❌ 写死在代码 | ✗ 需迁移 |
| 项目仓库路径 | `CLAUDE.md` / `start-claude.sh` 硬编码 | ❌ 写死在代码 | ✗ 需迁移 |

## 五、缺少的通用化能力

| # | 缺口 | 对应阶段 |
|---|---|---|
| 1 | `config/` 配置层（workflow / users / projects / adapters） | P02 设计 → P07 落地 |
| 2 | 配置加载器（脚本统一读取配置） | P06 |
| 3 | 总控 Skill `zentao-dev-workflow` | P04 |
| 4 | Skill / Agent 个人级安装方案 | P04 |
| 5 | Workflow Continuation Protocol（CLAUDE.md 硬规则） | P03 |
| 6 | 项目级执行隔离 `execution/{project_key}/{task_id}/` | P08 |
| 7 | 任务状态统一模板（tasks / run-state / session / agent-report） | P04 + P08 |
| 8 | 项目/人员配置模板 | P07 |
| 9 | `.env.example` | P07 |
| 10 | 第二个项目验证（证明通用性） | P10 |

## 六、保护项（升级过程不得破坏）

| 项 | 状态 | 处理原则 |
|---|---|---|
| `scripts/jenkins_run.py` | **用户已修改未提交**（+842 行） | 只做增量配置化，保留用户改动 |
| `scripts/jenkins_run.py_a` | 用户备份副本 | 不动 |
| `scripts/start-claude.sh` | 用户新建未提交 | 迁移路径到配置，保留脚本 |
| `execution/3413/run-state.json` | 未提交 | 迁移到 `execution/jeebootx/3413/`，原文件保留副本 |
| `docs/3413/` | 已提交（W1 成果） | 保留 |
| `.claude/scheduled_tasks.lock` | 运行时产物 | 加入 `.gitignore` |
| 业务仓库脏文件 | sanitation 4 / upms 1 / web 0 / app 1 | 完全不动 |
| `.worktrees/jeebootx-ui-zt3413` | W1 成果 `1c302d6` | 不动 |

## 七、供 P02 的输入建议

1. **配置格式**：脚本需在 `python -I`（无第三方包）下运行 → 推荐 **JSON 主格式 + YAML 人类可读别名**，或纯 YAML 配合可选 PyYAML 依赖。（P02 定稿）
2. **配置加载顺序**：内置默认 → `config/workflow.yaml` → `config/projects/{key}.yaml` → `config/users/{id}.yaml` → `.env` 覆盖。
3. **执行状态隔离**：`execution/{project_key}/{task_id}/`，旧 `execution/{task_id}/` 在 P08 迁移并留软链/副本。
4. **Agent 参数化**：任务 ID、项目 key、状态路径改为 Skill 传入的上下文变量。
5. **Skill 安装**：开发源在 `{WORKFLOW_HOME}/.claude/skills/zentao-dev-workflow/`，通过 `install.sh` 复制/软链到 `~/.claude/skills/`。
