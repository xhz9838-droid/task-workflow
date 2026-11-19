# Repository & Release Audit — zentao-dev-workflow 双目录盘点与开发发布机制

> 只读盘点 · 2026-11-20 · 不涉及代码修改或 Git 操作

---

## 一、目录身份与 Git 状态

### 1.1 D:\WorkSpace\task-workflow（开发运行时目录）

| 属性 | 值 |
|---|---|
| Git Remote | **无**（未配置 origin） |
| 分支 | `main` |
| HEAD commit | `e434d29` — fix: 用户身份解析不再依赖 OS 用户名 |
| 最近 10 次提交 | 用户身份解析 → _config.py adapters → 清理测试代码 → Jenkins 无参数 Job → 发版流程编排 → dw-qa-engineer 升级 |
| 工作区状态 | **16 个已跟踪修改 + 7 个未跟踪文件 + 1 个 stash** |
| 安装记录指向 | `~/.claude/zentao-dev-workflow.home` = `D:/WorkSpace/task-workflow` |
| 个人数据 | 含 `.env`、`.zentao_token.json`、`execution/`、实时适配器配置、用户配置 `xuhongzu.yaml`、项目配置 `ai-platfrom.yaml`/`jeebootx.yaml` 等 |

### 1.2 D:\WorkSpace\lianzhu-skills\zentao-dev-workflow（发行版目录）

| 属性 | 值 |
|---|---|
| Git Remote | `origin` → `https://codeup.aliyun.com/.../lianzhu-skills.git` |
| 所属仓库 | `lianzhu-skills`（父仓库，多子项目 monorepo） |
| 分支 | `master` |
| HEAD commit | `c7536fd` — fix: SKILL.md --user 参数改为可选，禁止 $(whoami) 模式 |
| 最近 10 次提交 | SKILL.md --user 修复 → workhour v2 REST → 清理决策日期标注 → Phase 0.5 稳定性 → 任务驱动注册编排 → P0 安全改造 |
| 工作区状态 | **2 个已跟踪修改**：`agent-manager/models.py`（新增 WAITING_HUMAN 状态）、`skill/SKILL.md`（--user 修复） |
| 个人数据 | **不含** `.env`、`execution/`、token 文件、实时配置 |

---

## 二、关键差异矩阵

### 2.1 文件存在性差异

| 类别 | task-workflow 独有 | lianzhu-skills 独有 |
|---|---|---|
| 运行时数据 | `execution/`、`.env`、`.zentao_token.json` | — |
| 个人/项目配置 | `ai-platfrom.yaml`、`demo-react.yaml`、`jeebootx.yaml`、`xuhongzu.yaml`、`hitl.local.yaml`、`hitl.yaml`、`jenkins.yaml`、`notification.yaml`、`zentao.yaml` | —（只有 `.example` 模板） |
| 脚本 | `release_run.py`、`jenkins_run.py_a`（备份文件） | `register_from_task.py`（任务驱动注册脚本） |
| 项目级 Skill/Agent | `.claude/skills/`、`.claude/agents/` | —（Agent 在顶层 `agents/`） |
| 文档 | `docs/3413/`（任务实例文档）、`docs/architecture/final-architecture.md` | `docs/architecture/`（8 个架构设计文档）、`docs/architecture.md` |
| 测试 | 5 个文件 | 14 个文件（多 9 个） |
| 发行所需 | — | `agents/`（7 个 dw-* Agent 定义）、`skill/`（SKILL.md + references + templates） |

### 2.2 同名文件内容差异（按模块）

#### scripts/（9 个共同文件中 6 个不同）

| 文件 | task-workflow | lianzhu-skills | 差异类型 |
|---|---|---|---|
| `project_resolver.py` | **较新** — 含 `whoami` CLI、`_resolve_user_id()`、`_user_id_source()` | 旧版 — 原始 `current_user_id()` 无 source 返回 | **功能缺失** |
| `project_register.py` | **较新** — 含 `_try_resolve_user()` 回退 | 旧版 — 无自动用户解析 | **功能缺失** |
| `dispatch.py` | **较新** — 含 `WAITING_HUMAN` 状态支持 | 旧版 — 无 WAITING_HUMAN | **功能缺失** |
| `repo_check.py` | **较新** — 含 `detect_git_info()` 注册自动收集函数 | 旧版 — 无 Git 信息识别 | **功能缺失** |
| `jenkins_run.py` | **较新** — 含无参数 Job 回退 `/build` 逻辑 | 旧版 — 无此回退 | **功能缺失** |
| `migrate_runstate.py` | CRLF 行尾 | LF 行尾 | 仅行尾差异 |
| `_args.py`、`_config.py`、`_home.py` | ✓ 相同 | ✓ 相同 | 一致 |
| `audit.py`、`install.sh`、`notify.sh`、`start-claude.sh`、`zt.py` | ✓ 相同 | ✓ 相同 | 一致 |

#### agent-manager/（所有 Python 文件内容一致，仅行尾差异）

| 文件 | 状态 |
|---|---|
| `cli.py` 到 `zentao_reporter.py`（共 15 个） | ✓ 内容相同 |
| `human_decision/hitl_config.py` | CRLF vs LF 行尾差异 |
| `human_decision/reply_handler.py` | CRLF vs LF 行尾差异 |
| `human_decision/` 其他 13 个文件 | ✓ 内容相同 |
| `models.py` | lianzhu-skills 工作区有未提交修改（新增 `WAITING_HUMAN` 状态），**与 task-workflow committed 版本相同** |

#### 测试目录差异大

| 指标 | task-workflow | lianzhu-skills |
|---|---|---|
| 测试文件数 | 5 | 14 |
| `test_project_resolver_user.py` | ✓ 有 | ✗ 无（**缺失**） |
| `test_config_root.py` | ✗ 无 | ✓ 有 |
| `test_dispatch_state.py` | ✗ 无 | ✓ 有 |
| `test_project_resolver.py` | ✗ 无 | ✓ 有 |
| `test_project_register.py` | ✗ 无 | ✓ 有 |
| `test_register_from_task.py` | ✗ 无 | ✓ 有 |
| `test_registry_integration.py` | ✗ 无 | ✓ 有 |
| `test_repo_check.py` | ✗ 无 | ✓ 有 |
| `test_workflow_home.py` | ✗ 无 | ✓ 有 |
| `test_invocation.py` | ✗ 无 | ✓ 有 |
| `test_zt_project.py` | ✗ 无 | ✓ 有 |

> **结论**：lianzhu-skills 有更完整的测试套件（14 vs 5），但缺少 task-workflow 最新写的 `test_project_resolver_user.py`。

### 2.3 SKILL.md 三版本混乱

存在 **三个不同版本** 的 SKILL.md，MD5 各异：

| 位置 | 行数 | MD5 | 描述 |
|---|---|---|---|
| `~/.claude/skills/zentao-dev-workflow/SKILL.md` | **232** | `61d3ec0e...` | **实际运行版本** — 最完整，含未注册→注册引导→继续流程、L3 决策强制路由、阶段进度自动回写 |
| `task-workflow/.claude/skills/zentao-dev-workflow/SKILL.md` | **163** | `bad03a08...` | 旧版本 — 不含注册引导、无 L3 路由说明 |
| `lianzhu-skills/zentao-dev-workflow/skill/SKILL.md` | **162** | `033b74f9...` | 较新但精简 — 含我们的 `--user` 可选修复，但略短于 task-workflow |

**实际生效的是安装版（232 行）**，通过 `install.sh` 从某个时间点的 `skill/` 目录复制而来，是最完整但最旧的版本（不含最新 `--user` 修复）。

---

## 三、核心判断

### 3.1 哪个目录有最新有效代码

**task-workflow** 的 `scripts/` 包含最新功能代码（用户身份解析修复、WAITING_HUMAN、Git 信息识别），但它**没有 Git remote**，无法作为唯一开发源。

**lianzhu-skills** 有 Git remote、更完整的测试套件和 `register_from_task.py`，但关键脚本落后于 task-workflow。

| 模块 | 最新版本所在 |
|---|---|
| scripts/（核心业务逻辑） | **task-workflow**（6 个文件更新） |
| agent-manager/（Agent 执行引擎） | 两者相同（仅行尾差异） |
| tests/（测试） | **lianzhu-skills**（14 vs 5） |
| SKILL.md（Skill 指令） | **安装版**（~/.claude，232 行，含最完整的注册引导流程） |
| config/（实时配置） | task-workflow（独有） |
| agents/（Agent 定义） | lianzhu-skills（独有；task-workflow 在 `.claude/agents/` 下） |

### 3.2 当前实际运行版本

通过 `~/.claude/zentao-dev-workflow.home` 指向 `D:/WorkSpace/task-workflow`，所有脚本、配置、execution 数据均从 task-workflow 读取。

**安装的 SKILL.md 来自 task-workflow 的旧版本**（163 行 → 安装时变成 232 行，意味着安装脚本从某个更早的 task-workflow `skill/` 目录安装，当时 skill/ 尚未被移到 `.claude/skills/`）。

### 3.3 安全基线评估

**当前无法确定安全基线**，原因：

1. task-workflow 无 Git remote，无法推送/发布
2. lianzhu-skills 缺少 6 项关键功能更新（project_resolver whoami、_try_resolve_user、WAITING_HUMAN、detect_git_info 等）
3. SKILL.md 三版本不一致，安装版与实际开发版内容不同
4. task-workflow 有 16 个未提交修改，无法确认哪些已完成、哪些进行中
5. lianzhu-skills 的 `models.py` 有未提交的 WAITING_HUMAN 状态变更

---

## 四、差异分类

### 功能修改（需同步）

| 差异 | 说明 | 方向 |
|---|---|---|
| `project_resolver.py` whoami + _resolve_user_id | 用户身份解析不依赖 OS 用户名 | task-workflow → lianzhu-skills |
| `project_register.py` _try_resolve_user | 注册时自动解析用户 | task-workflow → lianzhu-skills |
| `dispatch.py` WAITING_HUMAN | 人工决策节点状态支持 | task-workflow → lianzhu-skills |
| `repo_check.py` detect_git_info | 注册自动收集 Git 信息 | task-workflow → lianzhu-skills |
| `jenkins_run.py` 无参数 Job 回退 | Jenkins 触发兼容性 | task-workflow → lianzhu-skills |
| `register_from_task.py` 整文件 | 任务驱动注册自动化 | lianzhu-skills → task-workflow |
| 测试套件（9 个缺失） | 完整测试覆盖 | lianzhu-skills → task-workflow |
| `test_project_resolver_user.py` | 新增的用户解析测试 | task-workflow → lianzhu-skills |

### 版本同步问题（非功能差异）

| 差异 | 说明 |
|---|---|
| `migrate_runstate.py`、`hitl_config.py`、`reply_handler.py` | 仅 CRLF/LF 行尾差异，内容相同 |
| SKILL.md 三版本 | 安装版最完整但缺最新修复；两个开发版各缺少不同部分 |
| CLAUDE.md | 内容相同 |

---

## 五、风险清单

| 风险 | 严重度 | 说明 |
|---|---|---|
| 开发源无 remote | **CRITICAL** | task-workflow 无法推送，代码仅存本地 |
| 发行目录功能落后 | **HIGH** | lianzhu-skills 缺失 6 项关键功能更新 |
| SKILL.md 三版本不一致 | **HIGH** | 实际运行 Skill 内容与开发版不同，可能导致行为差异 |
| 未提交修改堆积 | **MEDIUM** | task-workflow 16 个文件未提交，存在数据丢失风险 |
| agent-manager WAITING_HUMAN 变更未同步 | **MEDIUM** | lianzhu-skills models.py 有未提交修改，与 dispatch.py 状态不一致 |
| 安装指向开发目录 | **MEDIUM** | install 记录指向 task-workflow，个人数据与代码混存 |
| 无版本标签 | **LOW** | 两个仓库均无 git tag，无法确定稳定版本 |

---

## 六、推荐方案

### 6.1 目录职责重新划分

```
D:\WorkSpace\task-workflow/        ← 唯一开发源（DEV）
  ├── scripts/         ← 所有业务脚本
  ├── agent-manager/   ← Agent 执行引擎
  ├── .claude/skills/  ← Skill 定义（开发版）
  ├── .claude/agents/  ← Agent 定义（开发版）
  ├── agents/          ← Agent 定义（同步到发行版用，与 .claude/agents/ 保持一致）
  ├── skill/           ← Skill 目录（同步到发行版用，与 .claude/skills/ 保持一致）
  ├── config/          ← 模板配置（不含个人数据）
  ├── tests/           ← 测试
  └── execution/       ← 运行时数据（.gitignore）

D:\WorkSpace\lianzhu-skills\zentao-dev-workflow/  ← 发行版（RELEASE）
  ├── 从 task-workflow 单向同步（非直接开发）
  ├── 只包含：scripts/ agent-manager/ skill/ agents/ config/ tests/
  ├── 不含：.env execution/ 个人配置 real adapter YAML
  └── Git remote = origin，用于分发

~/.claude/skills/zentao-dev-workflow/  ← 安装目标（INSTALL）
  ├── 经 install.sh 从发行版目录安装
  └── ~/.claude/zentao-dev-workflow.home 指向运行时目录
```

### 6.2 单向下游同步流程

```
task-workflow (DEV)
    │
    │  1. 开发完成 → git commit + git tag
    │  2. 运行 sync 脚本
    ▼
lianzhu-skills/zentao-dev-workflow (RELEASE)
    │
    │  3. git commit + git tag
    │  4. 运行 install.sh
    ▼
~/.claude/skills/zentao-dev-workflow (INSTALL)
```

### 6.3 版本管理

| 动作 | 命令/流程 |
|---|---|
| 开发版本号 | `git tag -a v1.2.0 -m "..."` on task-workflow |
| 发行版本号 | `git tag -a zentao-dev-workflow/v1.2.0 -m "..."` on lianzhu-skills |
| 版本格式 | `v<major>.<minor>.<patch>`（语义化版本） |
| CHANGELOG | 每个 tag 记录变更摘要 |

### 6.4 安装与升级

| 场景 | 操作 |
|---|---|
| 全新安装 | `git clone lianzhu-skills` → `cd zentao-dev-workflow` → `scripts/install.sh` |
| 升级 | `git pull lianzhu-skills` → `cd zentao-dev-workflow` → `scripts/install.sh`（自动备份旧版） |
| 回滚 | `git checkout <旧tag>` → `scripts/install.sh` |
| 验证安装 | `python -I "{WF}/scripts/project_resolver.py" whoami` |

### 6.5 立即行动项（优先级排序）

| 优先级 | 行动 | 说明 |
|---|---|---|
| **P0** | 为 task-workflow 配置 Git remote | 否则代码仅存本地，无法协作/备份 |
| **P0** | 清理 task-workflow 未提交修改 | 区分完成的功能 vs 进行中的实验 |
| **P1** | 合并 SKILL.md 三版本 | 以安装版（232 行）为基，合并 `--user` 修复 |
| **P1** | 同步 task-workflow scripts/ 新功能到 lianzhu-skills | 6 个文件的功能更新 |
| **P1** | 同步 register_from_task.py 到 task-workflow | lianzhu-skills 独有的脚本 |
| **P2** | 合并测试套件 | 最终两边均为 15 个测试文件 |
| **P2** | 统一行尾约定 | 全部用 LF（`.gitattributes text=auto`） |
| **P2** | 创建版本标签 | 同步完成后打 tag |
| **P3** | 编写 sync 脚本 | 自动化 task-workflow → lianzhu-skills 同步 |

---

## 七、DevFlow AI 独立隔离方案

### 7.1 目录规划

```
D:\WorkSpace\devflow-ai/              ← DevFlow AI 开发源（独立仓库）
  ├── .git/                  ← 独立 Git 仓库
  ├── scripts/               ← 移植后的脚本（去掉 zentao 特定逻辑）
  ├── agent-manager/         ← 移植后的执行引擎
  ├── skill/                 ← Skill 定义
  ├── agents/                ← Agent 定义（通用化命名）
  ├── config/                ← 模板配置（无 zentao 硬编码）
  ├── tests/                 ← 测试
  └── docs/                  ← 文档

D:\WorkSpace\lianzhu-skills\devflow-ai/ ← DevFlow AI 发行版
  ├── 从 devflow-ai 单向同步
  └── Git remote = origin（lianzhu-skills monorepo）

~/.claude/skills/devflow-ai/            ← DevFlow AI 安装目标
~/.claude/agents/devflow-*/             ← DevFlow AI Agent 安装目标
```

### 7.2 隔离规则（硬性）

| 规则 | 说明 |
|---|---|
| 独立 Git 仓库 | `devflow-ai` 不与 `task-workflow` 共享历史 |
| 独立版本标签 | `devflow-ai/v1.0.0` 前缀区分 |
| 独立安装目录 | `~/.claude/skills/devflow-ai/`，不覆盖 `zentao-dev-workflow/` |
| 独立数据目录 | execution 根为 `devflow_execution/` 或由配置指定 |
| 独立配置文件 | `~/.claude/devflow-ai.json`（类比 `zentao-dev-workflow.json`） |
| 独立 Agent 命名 | `df-architect` 等前缀，不与 `dw-architect` 冲突 |
| 禁止自动双向同步 | 两端可以手动 cherry-pick Bug 修复，但无自动化同步 |

### 7.3 从 zentao-dev-workflow 建立基线

1. 确定一个稳定 commit（如同步完成后的 tag `v1.2.0`）
2. `git clone` task-workflow 该 tag 为临时目录
3. 移除 zentao 特定逻辑：禅道适配器、zt.py（保留通用 CLI 框架）
4. 移除 dw- 前缀 Agent 定义中的 jeebootx/ai-platfrom 项目特定指令
5. 重命名为通用 Agent（如 `df-architect`）
6. 清理 config/ 中的项目特定模板
7. 作为 `devflow-ai` 初始 commit

### 7.4 选择性 Bug 修复移植

```
zentao-dev-workflow 修复 → 人工评估是否适用于 devflow-ai
  ├── 通用执行引擎修复 → cherry-pick
  ├── 禅道/Jenkins 特定修复 → 跳过
  └── Agent 执行逻辑修复 → cherry-pick（去掉项目特定部分）
```

---

## 八、备注

- 本报告基于 2026-11-20 只读盘点
- 不包含 `.env`、token 等敏感内容
- git stash (`stash@{0}`) 未展开分析
- lianzhu-skills 的 `agent-manager/models.py` 未提交修改（WAITING_HUMAN）需决策：提交还是丢弃