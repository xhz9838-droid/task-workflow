# 项目注册与自动发现机制 — P01 现状盘点

> 2026-11-17 · 任务：Project Registry & Discovery（P01-P07）· 只读盘点
> 基线：927083e + 并行会话 task-workflow-31 在途改动（_home/_args/_config 等，见 §6）

## 一、现有能力（可直接复用）

### 1. 配置体系与加载器（`scripts/_config.py`，P02 通用化成果）
- 加载顺序：内置默认 → `config/workflow.yaml` → `config/adapters/*.yaml` → `config/projects/{key}.yaml` → `config/users/{id}.yaml` → `.env`（仅敏感项）
- `${VAR}` 环境变量替换（未定义明确报错）；PyYAML 缺失回退同名 .json
- API：`load_config(project_key, user_id, strict=True)`（合并 dict：`project`/`user`/adapters/`_root`）、
  `get/require`（点路径取值）、`resolve_repo(cfg, repo_key)`（仓库路径）、
  `exec_root(cfg, project_key, task_id)` → `execution/{project_key}/{task_id}`、
  `worktree_root`、`enabled_agents`、`integration_enabled`
- CLI：`python -I scripts/_config.py show|validate <project_key> [<user_id>]`

### 2. WORKFLOW_HOME 机制（task-workflow-31 在建，接口已冻结）
- `scripts/_home.py`：`resolve_workflow_home(...) -> (path, source)`（env → 用户级配置 → 安装记录 → 开发源 → 向上探测）+ `validate_home()`；Skill 安装目录永不为根
- `scripts/_args.py`：`parse_invocation(tokens)`（`#3415`→task_id + missing=[project_key]）与
  **`match_project(task_detail, projects)`**（禅道任务→项目配置归属匹配，唯一命中才返回）
- SKILL.md 已加第 0 步（定位工作流根）与参数独立解析约定；`project.zentao_project` 可选字段（项目 ID/名称，可列表）已入 project.example.yaml
- **本任务 P04 复用 `match_project`，不另写核心匹配逻辑**（已与 31 会话书面对齐）

### 3. ZenTao 适配（`scripts/zt.py` + 用户级 Skill 客户端）
- `zt.py detail --task <id>`：只读任务详情（本人任务校验 `whoami`+`assignedTo`），字段含
  `id/name/status/project/execution/executionName/story/.../assignedTo/desc` —— **`project`（禅道项目 ID）即自动发现的锚点**
- `zt.py progress`：阶段进度追加（统一 PUT + 读回核验）
- 客户端 `zentao._shared.client_api.ZenTaoClient`：`HttpMixin._request`（通用 REST）、`whoami`、
  `TasksMixin.list_tasks/task_detail/execution_tasks`、`UsersMixin.list_users/user_detail`、
  `ProductsMixin`、`ExecutionsMixin`（`POST /projects/<pid>/executions` 实证）、`BugsMixin`、`TestingMixin`
- 凭据：`~/.claude/skills/zentao/_shared/config.json`（gitignored），不新建账号、不重复配置

### 4. 项目配置规范（config/projects/{key}.yaml，jeebootx/demo-react 实例）
```yaml
project:
  key / name / root / baseline_branch
  repositories: [{key, path(${}引用), role, technology, enabled, build_command, test_command, lint_command}]
  tech_stack: {backend, frontend, mobile, database}
  agents: {dw-*: bool}
  integrations: {task_source, ci, notification}
  zentao_project: <ID|名称|列表>   # 31 在建可选字段
```
- **多仓库原生支持**（jeebootx：sanitation/upms/web/app 四仓库）✓ 任务验收 3 直接可满足
- 个人路径现状：`path` 用 `${JEEBOOTX_...}` 引用，实际值在 `.env`（机器级）——与任务要求的
  "用户本地路径配置（config/users/{id}.yaml）" 是两种机制，需做**优先级兼容**（见 §4）

### 5. 用户配置规范（config/users/{id}.yaml，gitignored 实例）
```yaml
user: {id, display_name}
task_source: {provider: zentao, account}
notification: {provider, enabled}
preferences: {language, timezone}
```
- 无路径映射字段 → **新增 `project_paths` 为兼容扩展**（不动既有键）

### 6. 其他可复用
- 执行状态：`execution/{project_key}/{task_id}/`（audit.jsonl / run-state.json / agent-reports…）+ agent-manager SQLite（任务锁/幂等）
- HITL 人工决策闭环（刚完成生产验收 A01/A02，含 D4-D8 修复）
- 测试体系：workflow 根 `tests/`（pytest，31 在建 3 件）+ `agent-manager/tests`（20）+ `agent-manager/human_decision/tests`（56）
- 审计：`scripts/audit.py`（execution/{project}/{task}/audit.jsonl）

## 二、缺失能力（对照任务目标）

| # | 缺失 | 对应任务节 |
|---|---|---|
| 1 | 项目注册入口（/workflow-register-project Skill + 注册 CLI） | 二.1 / 八 |
| 2 | `project_resolver.py` 统一项目解析（Skill/Agent/脚本共用一个映射逻辑入口） | 三.3 |
| 3 | `project_register.py`（创建/查重/校验/dry-run/安全更新/确认环节） | 三.4 |
| 4 | ZenTao 任务→project_key 自动发现链路（查任务→提取项目→匹配→上下文） | 二.2 / 四 |
| 5 | **用户级本地路径映射**（`project_paths`，多用户不同路径） | 三.2 |
| 6 | 仓库识别与路径校验（技术栈识别、Git 8 项校验、BLOCKED 语义） | 五 |
| 7 | 项目上下文统一下发（Agent 共享同一上下文） | 六 |
| 8 | 注册/解析/路径/集成的自动化测试 | 九 |
| 9 | 文档（注册/使用/故障排查/配置规范） | 十.15 |
| 10 | 禅道"当前用户可访问项目"列表查询（注册第 1 步）——现客户端无现成方法 | 二.1 / 四.1 |

## 三、匹配语义差异（须在 resolver 层解决）

`_args.match_project` 现状：任务的 `project/projectName/projectTitle` 与配置的
`key/name/zentao_project` 交集非空即算命中，**名称可单独命中**。
任务规格要求：**项目名称只能辅助识别，不能单独作为可靠依据**；优先级为
project_id 精确 > product_id 辅助 > 显式映射 > 名称辅助。

**处理方案（不另写核心匹配，包装+分级）**：
`project_resolver.py` 以 `match_project` 产出候选后做**可靠性分级**——
- 强命中：任务 `project`（ID）∈ 配置 `zentao_project`（ID 形态）→ 直接采用
- 弱命中：仅名称/key 文本相等 → **不自动采用，须用户确认**（或补 product_id 证据）
- 唯一候选但弱命中 → 询问；多候选 → 询问；无候选 → 提示未注册（给注册入口）
此为对 match_project 结果的解释层升级，匹配核心仍单点。

## 四、配置兼容性设计（关键决策）

1. **项目公共配置扩展**（`config/projects/{key}.yaml`）——只增不改：
   ```yaml
   project:
     zentao:                    # 新增块（zentao_project 旧字段保留兼容）
       project_id: 125          # 数字 ID（可靠锚点）
       product_ids: []          # 辅助匹配
   ```
   与 31 的 `zentao_project`（可为列表，ID/名称混）并存：解析时两者都读。
   任务建议结构中的 `repositories[].name/type/required/remote_url` → **映射到现有字段**：
   `name→key`、`type→technology`（识别值回填）、`required→enabled` 取反语义不引入，
   新增 `remote_url`（可选，Git remote 核验用）。**不改现有字段名**。
2. **用户路径映射**（`config/users/{id}.yaml`）——新增键：
   ```yaml
   project_paths:
     {project_key}:
       {repo_key}: D:/WorkSpace/xxx/yyy
   ```
   与 `.env` 路径机制的优先级：`project_paths[user][project][repo]` > `repositories[].path`（${ENV} 展开）。
   现有 jeebootx/demo-react（只用 ${ENV}）**零改动继续工作**（验收 9/10）。
3. **agents 结构**：现有为 map（`dw-*: bool`），任务建议为列表——**保留 map**（`enabled_agents()` 已依赖）。
4. **workflow.build.adapter**：现有 `integrations.ci: jenkins` 已表达——**不新增平行字段**。

## 五、最小改造方案（模块与数据流）

```text
/zentao-dev-workflow [#5001 | project 5001]
  └─ _args.parse_invocation           （31，已冻结）
  └─ zt.py detail --task 5001         （已有，只读+本人校验）
  └─ project_resolver.resolve(...)    （新：match_project 包装+可靠性分级+唯一性+enabled 校验）
  └─ _config.load_config(key, user)   （已有；扩展 project_paths 优先级）
  └─ repo_check.verify(cfg, user)     （新：技术栈识别 + Git 校验 + BLOCKED）
  └─ exec_root 初始化                 （已有 exec_root；识别失败不创建——前置校验）
  └─ 原 Agent 工作流（DAG/HITL/回写 全部不变）

/workflow-register-project
  └─ zentao 项目列表（新：client._request 只读 GET /projects，P04 实测端点）
  └─ project_register.plan(...)       （新：查重 project_key/project_id、技术栈识别、Git 校验、dry-run）
  └─ 用户确认（HITL/L3 语义沿用人工确认）
  └─ project_register.write(...)      （原子写：临时文件→校验→替换；失败不留半成品）
  └─ 注册报告 reports/PROJECT-REGISTRY-*.md
```

新增文件：
- `scripts/project_resolver.py`（解析 + 项目上下文 + 仓库校验的统一入口）
- `scripts/project_register.py`（注册 CLI：plan/apply、dry-run、查重、验证）
- `.claude/skills/workflow-register-project/SKILL.md`（新 Skill，不动现有 Skill 目录内容）
- `tests/test_project_resolver.py`、`tests/test_project_register.py`、`tests/test_repo_check.py`（沿用根 tests/ 约定）

修改文件（等 31 commit 后增量）：
- `scripts/_config.py`（`resolve_repo` 支持 project_paths 优先级 + `current_user` 解析）
- `config/projects/project.example.yaml`（zentao 块 + remote_url 注释）
- `config/users/user.example.yaml`（project_paths 模板）
- `.claude/skills/zentao-dev-workflow/SKILL.md`（接入 resolver 流程，保留 31 的第 0 步/参数解析）
- `scripts/zt.py`（新增只读 `project` 子命令：任务归属信息/可访问项目列表，不写禅道）

不动：`execution/` 历史、`agent-manager/human_decision/`、`jenkins_run.py`（除非映射 project 构建配置）、7 个 Subagents、DAG 语义、HITL。

## 六、风险与并行协调

| 风险 | 应对 |
|---|---|
| 31 会话在途改动（_home/_args/_config/SKILL/install/tests 等 9 改 2 新） | 已书面对齐分工：其范围=任意目录启动，不含项目注册；实现已冻结即将提交；**我等其 commit 后增量改共享文件**；其测试落根 `tests/`，我的新测试同目录不同文件 |
| `match_project` 名称可单独命中（与规格语义差） | resolver 层可靠性分级（§三），不改 31 的函数 |
| 禅道项目列表端点未实测（GET /projects） | P04 先只读实测；不可用则降级：由用户直接给 project_id/名称（注册 CLI 支持手填），**不猜** |
| 个人路径两套机制（.env ${VAR} vs project_paths） | 明确优先级+兼容（§四.2），jeebootx/demo-react 零改动 |
| 用户配置 gitignored 与"可进入 Git"的边界 | `config/users/{id}.yaml` 保持 gitignored（含路径=个人机器信息）；模板进 Git；凭据永不进 |
| 多项目映射同一禅道项目 | 注册时查重拒绝（明确报错）；解析时多命中→询问用户 |
| 执行安全红线（不 clone/push/checkout/task_finish…） | 仓库校验只读（status/remote -v）；注册仅写 config/；禅道仅只读查询 |
| Windows 路径形态（D:/、D:\、Git Bash /d/） | `_norm_path` 归一比较（_config 已有）；repo_check 复用 |

## 七、阶段计划（P02-P07 与验收映射）

| 阶段 | 内容 | 覆盖验收项 |
|---|---|---|
| P02 | project_resolver（解析/匹配分级/上下文/用户路径优先级）+ _config 扩展 | 5/6/7/8 |
| P03 | project_register（plan/apply/dry-run/查重/原子写/报告） | 1/2/3/4 |
| P04 | ZenTao 自动发现（zt.py project 子命令、项目列表、match_project 对接） | 5/6 |
| P05 | /workflow-register-project 新 Skill + /zentao-dev-workflow 单参数流程 | 1/5/6 |
| P06 | 测试（注册/解析/路径/集成/兼容，Mock 禅道） | 11/12/13 |
| P07 | 文档 + PROJECT-REGISTRY-IMPLEMENTATION/ACCEPTANCE 报告 | 14/15 |

依赖顺序：P02 → P03 → P04 → P05 → P06 → P07；P06 测试随各阶段同步编写（TDD）。
P02 起的共享文件改动等待 task-workflow-31 的 commit 通知。
