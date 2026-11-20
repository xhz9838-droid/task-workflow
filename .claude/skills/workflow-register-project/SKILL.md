---
name: workflow-register-project
description: 业务项目接入注册（Project Registry）。查询当前用户可访问的禅道项目，引导完成 project_key 确认、本地仓库路径配置、技术栈自动识别、Git 校验，生成项目公共配置与个人路径映射（config/projects/{key}.yaml + config/users/{id}.yaml），经用户确认后原子写入并输出注册报告。当用户提到"接入新项目"、"注册项目"、"/workflow-register-project"、"项目注册"、"新项目接入工作流"时使用。只读禅道、不覆盖既有配置、不 clone/checkout。
---

# workflow-register-project：业务项目接入注册

## 调用方式

```text
/workflow-register-project
```

也可自然语言（"把智慧环卫项目接入工作流"、"注册一个新项目"）。

## 第 0 步：定位工作流根（每次启动必做）

与 zentao-dev-workflow 相同：Skill 安装目录**不是**工作流仓库。统一解析：

```bash
python -I "{WF_CANDIDATE}/scripts/_home.py"   # 输出校验通过的工作流根 {WF}
```

候选来源优先级：`WORKFLOW_HOME` 环境变量 → `~/.claude/zentao-dev-workflow.json` →
安装记录 `~/.claude/zentao-dev-workflow.home` → 开发源 → 向上探测。全部落空→明确报错，**不猜测**。

## 注册流程（12 步）

### 1. 查询禅道项目（只读）

```bash
python -I "{WF}/scripts/zt.py" projects
```

展示 `id / name / status` 清单，请用户**选择**要接入的禅道项目（不替用户选）。

### 2. 确认项目标识 project_key

- 提示 project_key 命名（字母数字`_-`，如 `smart-sanitation`）；由用户确认，**不代填**。
- 查重由脚本执行（project_key 与禅道项目 ID 均不得与已有注册重复）。

### 3. 配置本地代码仓库路径

逐仓库收集：`repo_key`、本地绝对路径、角色（backend/frontend/mobile/database/fullstack）、
可选 remote_url（用于 Git 核验）。**一个项目允许多个仓库**。

### 4. 生成注册计划（只读，含识别与校验）

```bash
python -I "{WF}/scripts/project_register.py" plan \
  --project-key <key> --name "<项目名>" \
  --zentao-project-id <禅道项目ID> [--product-ids 7,8] \
  --repo <repo_key>=<本地路径>:<role>[:<remote_url>] ... \
  --user <当前用户ID> --out "{WF}/execution/_register/plan-<key>.json"
```

脚本自动完成：project_key 查重、禅道项目查重、**技术栈识别**（pom.xml→java-maven、
build.gradle→java-gradle、package.json→vue/react/uni-app、requirements.txt/pyproject.toml→python）、
Git 8 项校验（路径/目录/Git 特征/根一致/remote 一致/工作区可读/可访问/角色一致）。

### 5. 展示计划并逐项确认（**写入前必须**）

向用户展示：
- 项目公共配置内容（`config/projects/{key}.yaml` 将写入什么——**不含个人路径与凭据**）
- 个人路径映射（`config/users/{id}.yaml → project_paths` 将写入什么）
- 技术栈识别结果与 Git 校验结果（含 `dirty` 工作区提示，仅提示不处理）
- **注册指纹 fingerprint**（计划的 12 位摘要）

用户确认（拒绝 → 终止，不写任何文件）。BLOCKED/mismatch 校验项必须先由用户处理后重新 plan。

### 6. 原子写入

```bash
python -I "{WF}/scripts/project_register.py" apply \
  --plan "{WF}/execution/_register/plan-<key>.json" --confirm <fingerprint>
```

- 指纹不一致 → 拒绝执行（计划已变更须重新确认）
- 写入仅两处：`config/projects/{key}.yaml`（新建）、`config/users/{id}.yaml`（仅新增 project_paths 键）
- **已存在的用户路径映射一律不覆盖**（冲突报错，由用户处理）
- 失败不留半成品（临时文件原子替换）

预览模式：`apply --dry-run`（打印将写入内容，不落盘）。

### 7. 输出注册报告

生成 `reports/project-registry-{key}.md`（或输出到对话），包含：禅道项目信息、project_key、
仓库清单与技术栈、Git 校验结果、写入的文件、指纹、遗留问题（如 dirty 工作区）。

## 安全红线（全程）

- 禅道**只读**（projects 列表 / 任务查询）；不建项目、不写任务、不执行 task_finish/task_close
- 不自动 clone / checkout / 切分支 / 改 remote / push / 清理工作区
- 不覆盖任何既有配置（项目配置已存在 → 拒绝重建；用户映射已存在 → 拒绝覆盖）
- 凭据（禅道/钉钉/Jenkins）**永不**写入任何配置
- 校验失败（路径不存在、非 Git 仓库、remote 不一致）→ BLOCKED 报告用户处理，**不自动修复**

## 与日常开发的衔接

注册完成后，用户即可：

```text
/zentao-dev-workflow #5001          # 自动发现项目
/zentao-dev-workflow <key> 5001     # 显式指定项目
```

两种方式进入同一套解析：`scripts/project_resolver.py`（唯一项目映射入口）。

## 故障排查

| 现象 | 处理 |
|---|---|
| `project_key 已存在` | 换 key，或用现有配置；本流程不覆盖重建 |
| `禅道项目 X 已注册到 Y` | 不允许多对一映射；如确需改归属，人工编辑配置 |
| `仓库 ... 校验 BLOCKED` | 按提示修复（路径/Git/remote）后重新 plan |
| `指纹不匹配` | 计划已变化，重新执行 plan 并用新指纹确认 |
| `拒绝覆盖：用户已有路径映射` | 人工决定保留或手工修改 config/users/{id}.yaml |
| 找不到工作流根 | 设置 `WORKFLOW_HOME` 或运行 `scripts/install.sh` 写入安装记录 |
