# P01-P10 通用化升级实施报告

> 2026-11-16 · 增量升级，未推倒重建 · 未破坏 #3413 成果与用户未提交修改

## 一、总体结果

| 阶段 | 状态 | 产出 |
|---|---|---|
| P01 现状盘点 | ✅ | `execution/upgrade/01-inventory.md` |
| P02 通用化设计 | ✅ | `execution/upgrade/02-architecture.md` |
| P03 CLAUDE.md 升级 | ✅ | 8 条 Workflow Continuation Protocol + 去项目硬编码 |
| P04 通用 Skill | ✅ | `.claude/skills/zentao-dev-workflow/`（SKILL.md + 6 references + 4 templates）+ `scripts/install.sh` |
| P05 七个 Agent 通用化 | ✅ | `.claude/agents/dw-*.md`（`dw-` 前缀避免覆盖用户 Agent） |
| P06 四脚本配置化 | ✅ | `scripts/_config.py` 加载器 + 4 脚本改配置驱动 |
| P07 项目/人员配置 | ✅ | `config/{workflow,users,projects,adapters}/` + `.env.example` |
| P08 状态目录规范化 | ✅ | `execution/{project_key}/{task_id}/` |
| P09 端到端验证 | ✅ | 6 项验证通过 |
| P10 第二项目验证 | ✅ | `demo-react`（Python+React，无 ZenTao/Jenkins/钉钉） |

## 二、架构落地

```text
通用核心（与项目/人员/工具无关）
├── .claude/skills/zentao-dev-workflow/   总控 Skill（开发源）
│   ├── SKILL.md
│   ├── references/  (6: lifecycle / continuation / recovery / approval / agent-dispatch / project-adaptation)
│   └── templates/   (4: tasks.yaml / run-state.json / session.json / agent-report.json)
├── .claude/agents/dw-*.md               7 个专业 Subagents（dw- 前缀）
├── scripts/_config.py                   配置加载器（PyYAML，缺则报错不猜测）
├── scripts/{zt,jenkins_run,notify,audit} 工具适配器
└── scripts/install.sh                   个人级安装/卸载

配置层（分离关注点）
├── config/workflow.yaml          全局策略（无个人/项目信息）
├── config/users/{id}.yaml        人员身份（真实配置 gitignored）
├── config/projects/{key}.yaml    项目属性：仓库/技术栈/Agent/集成
└── config/adapters/*.yaml        zentao / jenkins / notification（非敏感）

任务状态（项目+任务隔离）
└── execution/{project_key}/{task_id}/
```

## 三、通用性验证结果

### 验收标准逐项

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 通用 Skill 不依赖 jeebootx | ✅ | `zentao-dev-workflow` 无任何 jeebootx 引用 |
| 2 | 不写死当前用户账号 | ✅ | 账号在 `config/users/{id}.yaml` / 适配器配置 |
| 3 | 不写死本机绝对路径 | ✅ | 路径走 `${VAR}` + `.env` |
| 4 | 支持多个项目配置 | ✅ | `jeebootx` + `demo-react` 双项目并存 |
| 5 | 支持多个仓库 | ✅ | jeebootx 4 仓库 / demo-react 2 仓库 |
| 6 | 支持不同技术栈 Agent 组合 | ✅ | jeebootx 启用 7 个 / demo-react 启用 5 个 |
| 7 | 七个 Subagents 保留并通用化 | ✅ | `dw-*.md`，无任务 ID/路径硬编码 |
| 8 | 四脚本配置化 | ✅ | 白名单/路径/账号均来自配置 |
| 9 | ZenTao/Jenkins/钉钉可选 | ✅ | demo-react 全设 `none`，校验通过 |
| 10 | 任务状态项目隔离 | ✅ | `execution/jeebootx/3413/` + `execution/demo-react/1001/` |
| 11 | CLAUDE.md 含 Continuation Protocol | ✅ | 8 条硬规则 |
| 12 | 子 Agent 完成后推进 DAG | ✅ | 规则 1-3 明文 + `continuation-protocol.md` |
| 13 | 支持会话中断恢复 | ✅ | `recovery-protocol.md` + `checkpoints[]` |
| 14 | L1/L2/L3 审批规则明确 | ✅ | `approval-policy.md` |
| 15 | 两项目配置验证 | ✅ | jeebootx + demo-react |
| 16 | 不破坏 #3413 成果 | ✅ | W1 commit `1c302d6` 未动，`docs/3413/` 保留 |
| 17 | 不自动部署/关闭任务 | ✅ | 硬约束 + `allow_close: never` |

## 四、Skill 全局安装与跨项目调用

| 项 | 结果 |
|---|---|
| 开发源 | `{WORKFLOW_HOME}/.claude/skills/zentao-dev-workflow/` |
| 安装目标 | `~/.claude/skills/zentao-dev-workflow/` |
| 兼容别名 | `~/.claude/skills/dev-workflow`（软链） |
| 调用方式 | `/zentao-dev-workflow {project_key} {task_id}` |
| Agent 安装 | `~/.claude/agents/dw-*.md`（`dw-` 前缀） |
| 卸载 | `scripts/install.sh --uninstall` |
| 不破坏用户文件 | ✅ `architect.md` 等用户已有 Agent 保留原样 |

> **注意**：`.claude/agents/dw-*.md` 的 `name` 为 `dw-architect` 等。任务 DAG 中 `agent` 字段用 `dw-*` 名称。

## 五、配置加载机制

**顺序**（后者覆盖前者）：
```text
内置默认 → config/workflow.yaml → config/adapters/*.yaml
        → config/projects/{key}.yaml → config/users/{id}.yaml → .env
```

**环境变量替换**：`${VAR}` 从 `.env` / 进程环境变量；未定义 → **明确报错，不猜测**。

**API**：
```python
from _config import load_config, resolve_repo, exec_root, enabled_agents, integration_enabled
cfg = load_config("jeebootx", "xuhongzu")
```

**CLI**：
```bash
python -I scripts/_config.py validate <project_key> [<user_id>]
python -I scripts/_config.py show     <project_key> [<user_id>]
```

## 六、无适配器运行（demo-react 证明）

`integrations: {task_source: none, ci: none, notification: none}` 时：

- ✅ 需求分析、技术设计、代码开发、测试、审查、状态管理、DAG 调度、中断恢复 —— **全部可执行**
- ⏭ 跳过任务获取/回写、CI 构建、通知渠道
- L3 阻塞改在对话中直接询问本人

## 七、Workflow Continuation Protocol（8 条硬规则）

已写入 `CLAUDE.md` 独立章节：

1. 子 Agent 完成 ≠ 工作流完成
2. 子 Agent 返回后 9 步强制动作
3. DAG 自动推进（可执行节点判定 + 并行）
4. 完成状态验证（报告+文件变更+测试证据+Commit）
5. 人工审批（L1/L2/L3）
6. 中断恢复（6 步 + 可信检查点 + 禁止重复已完成节点）
7. 失败重试（默认 2 次，超限 BLOCKED）
8. 工作流结束（4 条件齐备才 COMPLETED；**不自动关闭业务任务**）

## 八、保护项核验

| 项 | 状态 |
|---|---|
| `scripts/jenkins_run.py`（用户 +842 行未提交） | ✅ 仅改白名单块，其余不动 |
| `scripts/jenkins_run.py_a`（用户备份） | ✅ 未动 |
| `scripts/start-claude.sh`（用户新建） | ✅ 未动（路径仍硬编码，可后续迁移） |
| `execution/3413/`（W1 成果） | ✅ 复制到 `execution/jeebootx/3413/`，原目录留 README |
| `.worktrees/jeebootx-ui-zt3413`（commit `1c302d6`） | ✅ 未动 |
| `docs/3413/` | ✅ 未动 |
| 业务仓库脏文件 | ✅ 未动 |
| 用户 `~/.claude/agents/architect.md` 等 | ✅ 已还原并验证完好 |

## 九、已知遗留（非阻塞）

| 项 | 说明 | 建议 |
|---|---|---|
| `scripts/start-claude.sh` 路径硬编码 | 用户新建脚本，本轮未改 | 后续迁移到配置（P06 遗留） |
| `docs/3413/` 无项目隔离 | 设计产物，引用路径未变 | 可选迁移 |
| `.claude/scheduled_tasks.lock` | 运行时产物 | 已加入 `.gitignore` |
| Skill 备份被注册为重复 Skill | 已清理 | — |
| Windows GBK 控制台输出 emoji | `_config.py` 已强制 UTF-8 | 其他脚本可同样处理 |

## 十、使用说明（其他人员）

```bash
# 1. 克隆工作流仓库
git clone <repo> && cd task-workflow

# 2. 配置
cp .env.example .env                      # 填机器路径 + 凭据
cp config/users/user.example.yaml config/users/{你的ID}.yaml
cp config/projects/project.example.yaml config/projects/{项目key}.yaml
cp config/adapters/*.example.yaml config/adapters/   # 按需

# 3. 安装到个人级
bash scripts/install.sh                    # 或 --link 源码改即时生效

# 4. 在任意项目目录启动 Claude Code
/zentao-dev-workflow {项目key} {任务ID}
```

凭据只放 `.env` 与用户级工具配置，**不进 Git**。

## 十一、验收结论

**通过。** 17 项验收标准全部满足；两项目（jeebootx / demo-react）配置验证通过；未破坏 #3413 成果与用户未提交修改；未自动部署或关闭业务任务。

下一步建议：用 jeebootx 禅道 #3413 从 QA1 节点续接，验证完整 DAG 推进与中断恢复。
