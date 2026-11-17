# 项目适配（Project Adaptation）

> 项目配置加载、技术栈适配、无适配器运行。

## 工作流根目录解析（WORKFLOW_HOME）

Skill 安装目录不含 `config/`、`execution/`，业务项目目录也不是工作流根。
所有路径以**工作流根**为锚，由 `scripts/_home.py` 统一解析（优先级命中即止）：

| 优先级 | 来源 | 无效时 |
|---|---|---|
| 1 | 环境变量 `WORKFLOW_HOME` | **明确报错**（不静默回落） |
| 2 | 用户级配置 `~/.claude/zentao-dev-workflow.json` → `workflow_home` | **明确报错** |
| 3 | 安装记录 `~/.claude/zentao-dev-workflow.home`（install.sh 写入） | 跳过，继续下一级 |
| 4 | Skill 开发源（脚本所在仓库，须通过校验） | 跳过，继续下一级 |
| 5 | 从当前目录向上探测（须同时含 `config/workflow.yaml` + `scripts/_config.py`） | 全部落空 → 报错询问用户 |

校验规则：必须同时存在 `config/workflow.yaml` 与 `scripts/_config.py`；
Skill 安装目录（`~/.claude/skills/**`）永远不是工作流根。

```bash
python -I scripts/_home.py            # 打印解析到的工作流根
python -I scripts/_home.py --json     # {"home": ..., "source": ...}
python -I scripts/_home.py --check    # 校验结构
```

`.env` 中的 `WORKFLOW_HOME` 不参与解析优先级；若与解析结果不一致 → 配置冲突，明确报错。

## 调用参数解析

`scripts/_args.py`：`project_key` 与 `task_id` **独立解析**：

- `#3415` / `3415` → 仅任务号；`project_key` 缺失，**不推断**
- `jeebootx 3415` / `3415 jeebootx` → 两者齐备
- `project_key` 缺失时经禅道任务查询验证归属（`zt.py detail` + `_args.py match-project`），
  唯一命中才使用；否则询问用户。项目侧可选 `project.zentao_project`（项目 ID/名称/列表）
  提供归属标识。

## 项目配置结构

`config/projects/{project_key}.yaml`：

```yaml
project:
  key: jeebootx
  name: jeebootx
  root: "${JEEBOOTX_ROOT}"
  baseline_branch: dev

  repositories:
    - key: backend
      path: "${JEEBOOTX_BACKEND}"
      role: backend
      technology: java-spring-boot
      build_command: "mvn -q clean package -DskipTests"
      test_command: "mvn test"
      lint_command: ""
      enabled: true
    - key: web
      path: "${JEEBOOTX_WEB}"
      role: frontend
      technology: vue
      build_command: "npm run build"
      lint_command: "npm run lint:eslint"
      enabled: true

  tech_stack:
    backend: Java
    frontend: Vue
    database: MySQL

  agents:
    architect: true
    database: true
    java-backend: true
    web-frontend: true
    mobile-app: true
    qa-engineer: true
    integration-reviewer: true

  integrations:
    task_source: zentao        # zentao | other | none
    ci: jenkins                # jenkins | other | none
    notification: dingtalk     # dingtalk | other | none
```

## 环境变量替换

配置中 `${VAR}` 从 `.env` 或进程环境变量替换。

```yaml
project:
  root: "${PROJECTKEY_ROOT}"     # .env 定义 PROJECTKEY_ROOT=<本机项目路径>
```

**规则**：
- 未定义的变量 → **明确报错**，不猜测
- 模板文件用 `${VAR}` 占位，真实配置用实际值或环境变量

## 配置加载器 API

`scripts/_config.py`：

```python
workflow_root() -> str                       # 工作流根（统一解析，见 _home.py）
load_config(project_key, user_id) -> dict        # 合并后配置
resolve_repo(cfg, repo_key) -> str               # 仓库绝对路径
exec_root(cfg, project_key, task_id) -> str      # execution/{project}/{task}
worktree_root(cfg) -> str
enabled_agents(cfg) -> list[str]
integration_enabled(cfg, name) -> bool
require(cfg, path, hint) -> Any                  # 缺则报错
```

## 技术栈适配

Agent 定义保持通用。技术栈特定知识来源：

| 来源 | 位置 |
|---|---|
| 项目规范 | `{repo}/CLAUDE.md`、`{repo}/AGENTS.md` |
| 构建/测试命令 | `config/projects/{key}.yaml → repositories[].build_command` 等 |
| 技术栈标签 | `config/projects/{key}.yaml → tech_stack{}` |
| 设计产物 | `design/openapi.yaml`、`design/ddl.sql` |

**禁止**把 jeebootx 的技术栈/仓库结构作为其他项目的默认事实。

## 多仓库支持

- 一个项目可有多个仓库（backend / frontend / mobile / …）
- 仓库路径**允许分别配置**，不要求统一父目录
- 每仓库独立 `role` / `technology` / `build_command` / `test_command`
- 不允许假设所有业务仓库共存于同一父目录

## 无适配器运行

工作流核心**不依赖**任何外部工具适配器：

| integrations.* | 行为 |
|---|---|
| `task_source: none` | 从 `task-context.md` 或人工输入获取任务；跳过进度回写 |
| `ci: none` | 跳过 CI 阶段；本地 lint/build/test 代替 |
| `notification: none` | L3 阻塞改在对话中直接询问本人 |

**仍可执行**：需求分析、技术设计、代码开发、测试、代码审查、状态管理、DAG 调度、中断恢复。

## 单仓库项目

```yaml
project:
  key: my-app
  repositories:
    - key: app
      path: "${MY_APP_ROOT}"
      role: fullstack
      technology: python-fastapi
      enabled: true
  agents:
    architect: true
    database: true
    java-backend: false     # 非 Java
    python-backend: true    # 自定义 Agent（若存在）
    web-frontend: false
    mobile-app: false
    qa-engineer: true
    integration-reviewer: false
```

## 项目配置校验

启动前必须校验：

1. `project.key` 与文件名一致
2. `repositories[].path` 实际存在且为 Git 仓库
3. `agents{}` 中启用的 Agent 在 `.claude/agents/` 存在
4. `integrations.*` 对应的 `config/adapters/*.yaml` 存在（若非 `none`）
5. `repositories[].build_command` 等命令可执行（可选，不阻塞启动）

**任一失败 → 明确报告缺失项，不猜测。**

## 项目配置变更

- 新增项目：复制 `config/projects/project.example.yaml` → `config/projects/{key}.yaml`，填实际值
- 修改项目：改 YAML，不改通用核心
- 删除项目：删除 YAML（任务状态保留）

## 凭据隔离

| 项 | 位置 | 是否入库 |
|---|---|---|
| Jenkins URL/用户/Token | `.env` | ❌ |
| ZenTao 账号密码 | `~/.claude/skills/zentao/_shared/config.json` | ❌ |
| 钉钉 AppKey/Secret | `~/.cc-connect/config.toml` | ❌ |
| 项目路径 | `.env`（`${VAR}` 引用） | ❌ |
| 项目配置结构 | `config/projects/{key}.yaml` | ✅（无凭据） |
| 模板 | `config/projects/project.example.yaml` | ✅ |

**禁止**：Token 写入 YAML 示例、Skill、Agent、任务报告。
**禁止**：把某个人的凭据复制给其他使用者。
