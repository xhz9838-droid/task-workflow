# 项目注册与自动发现（Project Registry & Discovery）使用文档

> 面向团队成员：如何接入新项目、日常如何只用任务号启动、配置规范与故障排查。

## 一、能力概览

| 能力 | 入口 |
|---|---|
| 新项目接入注册 | `/workflow-register-project`（或 `scripts/project_register.py` CLI） |
| 任务→项目自动发现 | `/zentao-dev-workflow #5001`（resolver 自动匹配） |
| 统一项目解析（所有 Agent/脚本共用） | `scripts/project_resolver.py` |
| 仓库识别与 Git 校验 | `scripts/repo_check.py` |
| 禅道只读查询（项目列表/任务归属） | `scripts/zt.py projects` / `zt.py project --task` |

## 二、首次接入新项目

```text
/workflow-register-project
```

流程：查询可访问禅道项目 → 选择 → 确认 project_key → 配置本地仓库路径（支持多仓库）
→ 生成计划（自动识别技术栈 + Git 8 项校验 + 查重）→ **展示计划并由您确认** → 原子写入 → 注册报告。

等价 CLI（脚本直用）：

```bash
python -I scripts/project_register.py plan \
  --project-key smart-sanitation --name "智慧环卫管理平台" \
  --zentao-project-id 125 \
  --repo backend=D:/WorkSpace/ss/backend:backend:git@example.com:team/ss-backend.git \
  --repo frontend=D:/WorkSpace/ss/ui:frontend \
  --user xuhongzu --out execution/_registry/plan-smart-sanitation.json

# 确认指纹（plan 输出的 fingerprint）后：
python -I scripts/project_register.py apply \
  --plan execution/_registry/plan-smart-sanitation.json --confirm <fingerprint>
```

- `apply --dry-run` 只预览不写入
- 指纹与计划不一致会拒绝执行；用户拒绝确认 → 不写任何文件

## 三、配置规范

### 1. 项目公共配置 `config/projects/{project_key}.yaml`（可进 Git）

```yaml
project:
  key: smart-sanitation            # 唯一标识（注册时查重）
  name: 智慧环卫管理平台
  baseline_branch: main
  enabled: true                    # 可选；false = 解析时视为禁用
  zentao:                          # 禅道归属（自动发现的可靠锚点）
    project_id: 125                # 禅道项目 ID（精确匹配）
    product_ids: [7]               # 可选，辅助匹配
    # 兼容旧字段：zentao_project: [125, "旧名称"]（ID/名称列表）
  repositories:
    - key: backend                 # 仓库标识（原 name 语义）
      role: backend                # backend|frontend|mobile|database|fullstack
      technology: java-maven       # 注册时自动识别（pom.xml→java-maven 等）
      enabled: true
      remote_url: "git@example.com:team/ss-backend.git"   # 可选，Git 核验用
  tech_stack: { backend: java-maven, frontend: vue }
  agents: { dw-architect: true, dw-java-backend: true, ... }
  integrations: { task_source: zentao, ci: none, notification: none }
```

**不含**个人绝对路径与任何凭据。（兼容：旧式 `repositories[].path: "${ENV_VAR}"` 继续有效。）

### 2. 用户本地路径 `config/users/{user_id}.yaml`（**不进 Git**）

```yaml
user:
  id: xuhongzu
project_paths:                     # 同一项目不同人员路径可不同
  smart-sanitation:
    backend: D:/WorkSpace/ss/backend
    frontend: D:/WorkSpace/ss/ui
```

优先级：`project_paths` > 项目配置 `repositories[].path`（`${ENV}` 展开）。
注册脚本只**新增** project_paths 键，已有映射一律拒绝覆盖。

### 3. 当前用户解析（不猜测）

显式 `--user` > 环境变量 `WORKFLOW_USER_ID` > `~/.claude/zentao-dev-workflow.json` 的 `user_id` → 否则明确报错。

## 四、日常开发（只用任务号）

```text
/zentao-dev-workflow #5001
```

流程：解析任务号 → `zt.py project --task 5001`（只读、仅本人任务）→
`project_resolver.match`（project_id 精确 > product_id 辅助 > 显式映射 > 名称仅辅助）→

- **唯一可靠命中** → 加载项目配置 + 您的路径映射 → 仓库校验 → 初始化 `execution/{project_key}/{task_id}/` → 启动原 Agent 工作流
- **仅名称命中** → 请您确认（名称不能单独作为可靠依据）
- **多候选** → 请您选择
- **无命中** → 提示未注册，提供 `/workflow-register-project` 入口；**不创建 execution、不猜测项目**

显式指定仍然可用：`/zentao-dev-workflow smart-sanitation 5001`。

## 五、仓库识别与校验

技术栈识别（标志文件）：`pom.xml`→java-maven、`build.gradle`→java-gradle、
`package.json`→vue/react/node（按依赖细分）、`manifest.json`+dcloudio→uni-app、
`requirements.txt`/`pyproject.toml`→python、无标志→unknown（不猜测）。

Git 校验（只读）：路径存在、是目录、Git 特征、Git 根与配置路径一致、remote 与注册一致、
工作区状态可读、可访问、角色一致。结果分级：`ok` / `mismatch`（不一致）/ `blocked`（缺环境）。
**系统绝不**：clone、checkout、切分支、改 remote、push、清理工作区、自动修复路径。

## 六、故障排查

| 现象 | 原因与处理 |
|---|---|
| `project_key 已存在` | 该 key 已注册；换 key 或直接使用现有配置（不覆盖重建） |
| `禅道项目 X 已注册到 Y` | 一个禅道项目只允许映射一个 project_key；确需变更请人工编辑配置 |
| `仅名称辅助命中` | 系统按规格不自动采用名称匹配；请确认后显式指定 project_key |
| `仓库 ... BLOCKED：路径不存在` | 路径错误或未 clone；自行处理后重新注册/启动 |
| `remote 不一致` | 本地 remote 与注册信息不同；核实后更新配置或本地（系统不代改） |
| `指纹不匹配` | plan 之后计划有变；重新 plan 并用新指纹确认 |
| `拒绝覆盖：用户已有路径映射` | 保护既有配置；人工决定后直接编辑 config/users/{id}.yaml |
| `无法确定当前用户` | 设 `WORKFLOW_USER_ID` 或在 `~/.claude/zentao-dev-workflow.json` 配 `user_id` |
| `无法唯一识别项目` | 按提示选择；系统不猜测（安全阻断） |
| 找不到工作流根 | 设 `WORKFLOW_HOME` 或重跑 `scripts/install.sh`（写安装记录） |

## 七、安全说明

- 禅道查询全部**只读**；注册不写禅道、不建项目、不改任务状态（task_finish/task_close 一律禁止）
- 项目查询与注册只使用当前账号有权限的禅道数据（本人任务校验）
- 凭据（禅道/钉钉/Jenkins token）不写入任何 Git 跟踪文件
- 注册写入原子化（临时文件→替换），失败不留半成品
- L3 人工决策闭环保持不变；项目注册的确认环节即人工审批点
