# P02 通用化架构设计

> 基于 `01-inventory.md` · 2026-11-16

## 一、分层边界

```text
┌─────────────────────────────────────────────────────────────┐
│  通用工作流核心（与具体项目/人员/工具无关）                      │
│  ├─ .claude/skills/zentao-dev-workflow/   总控 Skill          │
│  ├─ .claude/agents/*.md                   7 个专业 Subagents  │
│  ├─ scripts/_config.py                    配置加载器          │
│  ├─ scripts/{zt,jenkins_run,notify,audit} 工具适配器          │
│  └─ templates/                            状态/报告模板        │
└─────────────────────────────────────────────────────────────┘
            ▲ 读取                  ▲ 读取              ▲ 读取
┌───────────┴───────────┐ ┌────────┴────────┐ ┌───────┴─────────┐
│ config/workflow.yaml  │ │ config/users/   │ │ config/projects/│
│ 全局执行策略           │ │ {user_id}.yaml  │ │ {key}.yaml      │
│ 无个人/项目信息        │ │ 人员身份+偏好   │ │ 仓库/技术栈/Agent│
└───────────────────────┘ └────────┬────────┘ └────────┬────────┘
                                   │                   │
                          ┌────────┴───────────────────┴────────┐
                          │ config/adapters/*.yaml              │
                          │ zentao / jenkins / notification     │
                          │ （非敏感配置）                        │
                          └─────────────────┬───────────────────┘
                                            │ 敏感凭据走 .env / 用户级配置
                          ┌─────────────────┴───────────────────┐
                          │ .env（机器级凭据，gitignored）        │
                          │ ~/.claude/skills/zentao/_shared/... │
                          │ ~/.cc-connect/config.toml          │
                          └─────────────────────────────────────┘
```

## 二、配置加载顺序（后者覆盖前者）

```text
1. 脚本内置默认值
2. config/workflow.yaml              全局策略
3. config/adapters/{name}.yaml       工具适配器非敏感配置
4. config/projects/{project_key}.yaml 项目属性（仓库/技术栈/构建/Agent/集成）
5. config/users/{user_id}.yaml       人员身份与偏好
6. .env                               机器级凭据（最高优先级，只覆盖敏感项）
```

加载器（`scripts/_config.py`）提供：
- `load_config(project_key, user_id)` → 合并后的 dict
- `resolve_repo(project_key, repo_key)` → 仓库绝对路径
- `exec_root(project_key, task_id)` → `execution/{project_key}/{task_id}`
- 缺配置时**明确报错**，不猜测路径/账号/Job

## 三、配置文件职责

### 1. `config/workflow.yaml`（全局，无个人/项目信息）
```yaml
version: 1
workflow_name: zentao-dev-workflow
worktree_root: "${WORKFLOW_HOME}/../.worktrees"   # 可被 .env 覆盖
execution_root: "${WORKFLOW_HOME}/execution"
retry:
  max_attempts: 2
  strategy: exponential-backoff
concurrency:
  max_parallel_agents: 2
approval:
  levels: [L1, L2, L3]
  L3_requires_human: true
audit:
  enabled: true
  file: "audit.jsonl"
report_schema: "templates/agent-report.json"
continuation:
  enforce: true
```

### 2. `config/users/user.example.yaml`（模板，不含真实账号）
```yaml
user:
  id: "${USER_ID}"
  display_name: "${USER_DISPLAY_NAME}"
task_source:
  provider: zentao
  account: "${ZENTAO_USER}"      # 实际值从 .env 或用户配置读取
notification:
  provider: dingtalk
  enabled: true
preferences:
  language: zh-CN
  timezone: Asia/Shanghai
```

### 3. `config/projects/project.example.yaml`
```yaml
project:
  key: "${PROJECT_KEY}"
  name: "${PROJECT_NAME}"
  root: "${PROJECT_ROOT}"
  repositories:
    - key: backend
      path: "${PROJECT_ROOT}/backend"
      role: backend
      technology: java-spring-boot
      build_command: "mvn -q clean package -DskipTests"
      test_command: "mvn test"
      enabled: true
    - key: web
      path: "${PROJECT_ROOT}/web"
      role: frontend
      technology: vue
      build_command: "npm run build"
      enabled: true
  tech_stack: {}
  agents:
    architect: true
    database: false
    java-backend: true
    web-frontend: true
    mobile-app: false
    qa-engineer: true
    integration-reviewer: true
  integrations:
    task_source: zentao          # 或 none
    ci: jenkins                  # 或 none
    notification: dingtalk       # 或 none
```

### 4. `config/adapters/jenkins.example.yaml`
```yaml
jenkins:
  enabled: true
  base_url_env: "JENKINS_URL"    # 敏感值从 .env 读
  user_env: "JENKINS_USER"
  token_env: "JENKINS_TOKEN"
  jobs: ["<job-a>", "<job-b>"]   # 严格白名单，迁移自 jenkins_run.py
  param_names: {repo_url: REPO_URL, branch: GIT_BRANCH, ...}
  timeout_seconds: 1800
```

### 5. `config/adapters/zentao.example.yaml`
```yaml
zentao:
  enabled: true
  skill_dir_env: "ZENTAO_SKILL_DIR"    # 默认 ~/.claude/skills/zentao
  config_path_env: "ZENTAO_CONFIG"     # 默认 <skill_dir>/_shared/config.json
  manage_script: "<skill_dir>/zentao-tasks/scripts/manage_tasks.py"
  task_fields: {id: id, name: name, status: status, ...}
  write_guard: true
```

### 6. `config/adapters/notification.example.yaml`
```yaml
notification:
  enabled: true
  provider: dingtalk
  cc_connect_bin: "cc-connect"
  data_dir_env: "CC_CONNECT_DATA_DIR"  # 默认 ~/.cc-connect
  session_keys_file: "session.json"    # 每任务 session.json 提供 project/session key
  audit_sent: true
```

## 四、任务状态隔离

```text
execution/{project_key}/{task_id}/
├── tasks.yaml            # 任务 DAG（节点/依赖/Agent/文件所有权）
├── run-state.json        # 执行状态（阶段/节点/重试/阻塞/检查点）
├── session.json          # 会话与集成上下文（不含凭据）
├── task-context.md       # 任务上下文摘要
├── design/               # 需求/架构/DDL/OpenAPI
├── acceptance/           # 验收矩阵与结论
├── agent-reports/        # 各 Agent 结构化报告
├── test-reports/         # 测试报告
├── jenkins/              # Jenkins 构建摘要（原始日志 gitignored）
└── logs/                 # 运行日志
```

`run-state.json` 统一字段（模板见 `templates/run-state.json`）：
`project_key, task_id, stage, dag.nodes[], updated_at, retry_count, blockers[], checkpoints[], last_acceptance`

**迁移**：旧 `execution/3413/` → `execution/jeebootx/3413/`，保留 `execution/3413/README.md` 指向新路径（不删用户数据）。

## 五、Agent 调度策略

- **主 Agent** 唯一协调者，读 `tasks.yaml` 的 DAG，计算可执行节点。
- **启用过滤**：按 `projects/{key}.yaml → agents.{}` 决定哪些 Agent 参与。纯前端项目不派 `database`/`java-backend`。
- **技术栈适配**：Agent 定义保持通用；技术栈知识由项目内 `CLAUDE.md` 提供（Agent 提示中显式要求先读项目 CLAUDE.md）。
- **扩展**：新技术栈通过新增/替换 `.claude/agents/{tech}-*.md` 支持，不强制 7 个。

## 六、Workflow Continuation Protocol（硬规则）

写入 `CLAUDE.md` 独立章节，8 条规则（子 Agent 完成≠工作流完成 / 强制动作 / DAG 自动推进 / 完成状态验证 / L1-L3 审批 / 中断恢复 / 失败重试 / 工作流结束）。详见 P03。

## 七、当前项目（jeebootx）迁移方案

| 现状 | 迁移后 |
|---|---|
| `CLAUDE.md` 中 4 个仓库路径 | `config/projects/jeebootx.yaml → repositories[]` |
| `CLAUDE.md` worktree 路径 | `config/workflow.yaml → worktree_root` |
| `jenkins_run.py` WHITELIST | `config/adapters/jenkins.yaml → jobs[]`（jeebootx 值） |
| `start-claude.sh` 路径数组 | 从 `config/projects/jeebootx.yaml` 读取 |
| `execution/3413/` | `execution/jeebootx/3413/` |
| `docs/3413/` | 保留（设计产物），引用不变 |
| Agent commit 格式 `feat(3413)` | `feat(<TASK_ID>)`，由 Skill 传入 |

## 八、命名

- **开发源**：`{WORKFLOW_HOME}/.claude/skills/zentao-dev-workflow/`
- **安装目标**：`~/.claude/skills/zentao-dev-workflow/`
- **调用**：`/zentao-dev-workflow {project_key} {task_id}`
- **兼容别名**：`~/.claude/skills/dev-workflow` → 同一 Skill（软链/副本），覆盖 `§五` 的命名

## 九、通用性证明（P10）

新增 `config/projects/demo-react.yaml`（虚拟项目，不同技术栈/仓库组合），验证：
1. Skill 能加载新项目配置
2. 不触碰 jeebootx 的 execution 状态
3. 在无 ZenTao/Jenkins 配置时仍可执行需求分析/开发/审查阶段

## 十、风险与约束

| 风险 | 缓解 |
|---|---|
| 破坏 #3413 成果 | W1 commit `1c302d6` 在 worktree 不动；`docs/3413/` 保留 |
| 破坏用户未提交修改 | `jenkins_run.py`（+842 行）、`start-claude.sh`、`run-state.json` 增量修改，不 reset |
| 凭据泄露 | `.env`/真实用户配置 gitignored；模板只放变量名 |
| PyYAML 不可用 | 加载器 PyYAML 缺失时**明确报错**并提示 `pip install pyyaml`，不静默降级 |
| 过度抽象 | Linus 三问：配置分层是真实需求（多人员/多项目）；最简形式是 YAML dict；不破坏现有脚本调用方式 |
