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
├── skill/              # 总控 Skill（SKILL.md + references + templates）
├── agents/             # 7 个专业 Subagents（dw-*.md）
├── scripts/            # 工具适配器 + 配置加载器 + dispatch.py + migrate_runstate.py
├── agent-manager/      # 状态管理器（SQLite）+ runner/monitor/retry/verifier + HITL
├── config/             # 配置模板（.example.yaml）+ workflow.yaml
├── tests/              # 编排层测试（含故障注入）
├── CLAUDE.md           # 编排协议根规则（8 条硬规则）
└── .env.example        # 机器级凭据模板
```

## 安装到个人级

### 方式 1：用本目录的 install.sh

```bash
bash zentao-dev-workflow/scripts/install.sh
```

安装到 `~/.claude/skills/zentao-dev-workflow/` + `~/.claude/agents/dw-*.md`。

### 方式 2：用 lianzhu-skills 全局安装脚本

本 skill 尚未接入 `install-global.sh`。如需接入，在 `install-global.sh` 加一段：

```bash
# zentao-dev-workflow
rm -rf "$SKILLS_DST/zentao-dev-workflow"
cp -r "$SRC/zentao-dev-workflow/skill" "$SKILLS_DST/zentao-dev-workflow"
for n in dw-architect dw-database dw-java-backend dw-web-frontend dw-mobile-app dw-qa-engineer dw-integration-reviewer; do
  cp "$SRC/zentao-dev-workflow/agents/$n.md" "$USER_CLAUDE/agents/$n.md"
done
```

> 工作流根定位：`install.sh` 会写 `~/.claude/zentao-dev-workflow.home`，指向本 skill 所在
> 仓库（lianzhu-skills）。`config/` 与 `execution/` 需在工作流根下——若只用 skill 本体，
> `scripts/_home.py` 会探测本目录。**完整运行需把 config/scripts/agent-manager 一并部署**，
> 否则 dispatch.py/migrate_runstate.py 找不到依赖。

## 接入新项目

1. 复制 `config/projects/project.example.yaml` → `config/projects/{key}.yaml`，填项目属性
2. 复制 `config/users/user.example.yaml` → `config/users/{id}.yaml`，填人员身份
3. 复制 `.env.example` → `.env`，填机器级凭据（路径/Jenkins/ZenTao）
4. 运行 `scripts/_config.py validate {key} {user_id}` 校验
5. 或用 `scripts/project_register.py` 引导式注册（查禅道项目 + 自动识别技术栈）

接入后任意目录启动 Claude Code：`/zentao-dev-workflow {project_key} {task_id}`

## 安全约束

- **不进 git**：`.env`、`config/users/*.yaml`（非 example）、`config/projects/*.yaml`（非 example）、
  `execution/`、`agent-manager/logs/*.db`
- 凭据只放 `.env`（gitignored）或用户级工具配置
- 不自动部署、不自动重启、不自动 task_close
- task_finish 经 Verifier 门禁后可自动（须读回确认）

## 关键文档

| 场景 | 文件 |
|---|---|
| 总控流程 | `skill/SKILL.md` |
| 8 条硬规则 | `CLAUDE.md` |
| 派发协议（SQLite 唯一真相源） | `skill/references/continuation-protocol.md` |
| 中断恢复、僵尸 RUNNING 检测 | `skill/references/recovery-protocol.md` |
| L1/L2/L3 审批 | `skill/references/approval-policy.md` |
| Agent 调度 | `skill/references/agent-dispatch.md` |
| 项目适配 | `skill/references/project-adaptation.md` |

## 测试

```bash
# 编排层测试（含故障注入）
python -I tests/test_dispatch_state.py
python -I -m pytest tests/ -q

# agent-manager 集成测试
python -I agent-manager/tests/test_integration.py
```

## 与 zentao-* skill 族的关系

本 skill 复用 `zentao/_shared/` 的禅道客户端（task_source 适配器）、Jenkins、钉钉通知。
无 ZenTao 配置时仍可独立运行（需求分析/开发/测试/审查/状态管理）。
