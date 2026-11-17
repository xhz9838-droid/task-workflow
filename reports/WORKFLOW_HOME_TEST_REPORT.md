# 测试报告：zentao-dev-workflow 任意目录启动（Workflow Home 统一解析）

- 日期：2026-11-17
- 范围：`scripts/_home.py`、`scripts/_args.py`、`scripts/_config.py`、`scripts/audit.py`、`scripts/notify.sh`、`scripts/jenkins_run.py`、`scripts/install.sh`、SKILL.md / references、`config/projects/project.example.yaml`、`tests/`
- 约束遵守：未执行 Git Push、未部署、未重启服务、未执行禅道 task_finish/task_close；测试不触碰真实 `execution/` 与并行会话未提交文件

## 1. 问题与根因

执行 `/zentao-dev-workflow #3415` 时，Skill 在个人安装目录
`~/.claude/skills/zentao-dev-workflow`（只有 SKILL.md/references/templates，
不含 `config/`、`execution/`）寻找配置与状态目录。根因：SKILL.md 使用裸相对路径
`config/`、`execution/`、`scripts/` 且无工作流根定位机制；`scripts/_config.py` 只认
"脚本自身所在仓库"，Skill 安装目录与工作流仓库之间没有任何回溯通道。

## 2. 修复内容

| 文件 | 改动 |
|---|---|
| `scripts/_home.py` | 新增：工作流根统一解析 + 校验（stdlib-only，含 CLI） |
| `scripts/_args.py` | 新增：`project_key`/`task_id` 独立解析 + 禅道任务→项目归属匹配 |
| `scripts/_config.py` | `workflow_root()` 统一取根；`${WORKFLOW_HOME}` 自动注入；`.env` 值冲突明确报错 |
| `scripts/audit.py` / `notify.sh` / `jenkins_run.py` | 根路径统一经 `_home.py` 解析（失败回退脚本自定位，兼容旧行为） |
| `scripts/install.sh` | 写入/清除安装记录 `~/.claude/zentao-dev-workflow.home`（Windows 原生路径） |
| SKILL.md / `references/project-adaptation.md` / `workflow-lifecycle.md` | 第 0 步定位流程、参数解析规则、路径锚定 |
| `config/projects/project.example.yaml` | 可选 `zentao_project` 字段（任务归属验证用） |
| `tests/` | 43 项 pytest（tmp 隔离） |

## 3. 工作流根解析优先级（配置优先级）

`scripts/_home.py`，命中即止：

1. **环境变量 `WORKFLOW_HOME`** —— 显式指定；指向无效目录 → **明确报错**，不静默回落
2. **用户级工作流配置** `~/.claude/zentao-dev-workflow.json` → `workflow_home` —— 无效 → 明确报错
3. **安装记录** `~/.claude/zentao-dev-workflow.home`（`install.sh` 写入） —— 无效 → 跳过继续
4. **Skill 开发源 / 脚本所在仓库** —— 须通过校验才采用
5. **从当前目录向上探测** —— 须同时含 `config/workflow.yaml` + `scripts/_config.py`

校验规则：两标记文件必须同时存在；`~/.claude/skills/**`（Skill 安装目录）**永远不是**工作流根。
`.env` 中的 `WORKFLOW_HOME` 不参与优先级，与解析结果不一致 → `ConfigError`（防状态目录分裂）。

## 4. 实际支持的启动方式

| 启动位置 | 命中来源 | 说明 |
|---|---|---|
| 工作流仓库根/子目录 | 开发源 / 向上探测 | 无需任何配置 |
| Java 后端项目目录（jeebootx-sanitation） | 环境变量 / 用户级配置 / 安装记录 | 项目目录绝不误判为根 |
| Vue 前端项目目录（jeebootx-ui） | 同上 | 同上 |
| 无关目录 | 环境变量 / 用户级配置 / 安装记录 | 全无 → 明确报错并列出已尝试来源 |
| Skill 安装目录 | 永不命中自身 | 经上述外部来源定位 |

所有配置路径、执行状态（`{WF}/execution/{project_key}/{task_id}/`）、审计日志统一锚定定位后的工作流根。

## 5. 自动化测试矩阵与结果

执行：`python -m pytest tests/test_workflow_home.py tests/test_invocation.py tests/test_config_root.py -q`
结果：**43 passed**（另有并行会话的 `tests/test_project_resolver.py`、`test_repo_check.py` 同场 34 项亦通过，属其他任务范围）

| 测试要求 | 用例 | 结果 |
|---|---|---|
| 从工作流仓库启动 | `test_resolve_from_workflow_repo_root_dev_source` / `_by_probe` / `_subdir` | ✅ |
| 从 Java 后端项目目录启动 | `test_resolve_from_java_project_dir` | ✅ |
| 从 Vue 前端项目目录启动 | `test_resolve_from_vue_project_dir_by_user_config` | ✅ |
| 从无关目录启动 | `test_resolve_from_unrelated_dir_by_install_record` / `test_project_dir_mistaken_never` | ✅ |
| WORKFLOW_HOME 正确 | `test_workflow_home_env_correct` | ✅ |
| WORKFLOW_HOME 不存在 | `test_workflow_home_env_missing_falls_through`（回落）、`test_workflow_home_env_invalid_raises`（显式错误） | ✅ |
| 工作流根缺少必要配置 | `test_home_missing_required_config` / `_cli_exit_code` | ✅ |
| Skill 安装目录不包含 config/execution | `test_skill_install_dir_never_home` | ✅ |
| 缺少 project_key | `test_task_only_with_hash` 等（`#3415` → 仅任务号，`missing=[project_key]`，不推断） | ✅ |
| 项目配置不存在 | `test_project_config_missing_raises`（ConfigError） | ✅ |
| 不同 CWD 定位同一根 | `test_same_home_from_different_cwds` | ✅ |
| 各项目配置/execution 隔离、无重复错位目录、不覆盖并行状态 | `test_state_dirs_isolated_by_project_and_task`、`test_exec_root_under_located_root` | ✅ |
| 归属验证唯一命中 / 不唯一 | `test_match_by_zentao_project_id` 等、`test_cli_match_project_ambiguous_exit_code`（退出码 4 → 询问用户） | ✅ |
| Git Bash/MSYS 路径兼容 | `test_install_record_msys_path_accepted` | ✅ |
| .env 一致/冲突语义 | `test_dotenv_workflow_home_consistent_ok` / `_conflict_raises` | ✅ |

测试全部使用 tmp_path 假目录与注入参数，**不读写真实 `~/.claude`、真实 `execution/`**。

## 6. 真实环境冒烟证据

```text
# ① 从 Java 后端 / Vue 前端 / 工作流仓库目录解析（同一根）
$ cd /d/WorkSpace/jeebootx/jeebootx-ui && python -I /d/WorkSpace/task-workflow/scripts/_home.py --json
{"home": "d:\\workspace\\task-workflow", "source": "Skill 开发源 / 脚本所在仓库"}
$ cd /d/WorkSpace/jeebootx/jeebootx-sanitation && 同上 → d:\workspace\task-workflow

# ② 无关目录 + 安装记录（修复前的失败场景；WORKFLOW_HOME 未设置）
$ cd /c/Users/Administrator && python -I "$(cat ~/.claude/zentao-dev-workflow.home)/scripts/_home.py" --json
{"home": "d:\\workspace\\task-workflow", "source": "安装记录 C:\\Users\\Administrator\\.claude\\zentao-dev-workflow.home"}

# ③ 仅任务号解析（#3415 不是完整参数）
$ python -I scripts/_args.py parse "#3415"
{"project_key": null, "task_id": "3415", "missing": ["project_key"]}

# ④ 项目配置不存在 → 明确报错
$ python -I scripts/_config.py validate nope
❌ 配置错误：项目配置不存在：d:\workspace\task-workflow\config\projects\nope.yaml  (exit=3)

# ⑤ WORKFLOW_HOME 正确 / 无效
$ WORKFLOW_HOME=D:/WorkSpace/task-workflow python -I <orphan>/_home.py --json
{"home": "d:\\workspace\\task-workflow", "source": "环境变量 WORKFLOW_HOME"}
$ WORKFLOW_HOME=D:/not/exist python -I <orphan>/_home.py --json
❌ 工作流根目录无效：环境变量 WORKFLOW_HOME → D:/not/exist（目录不存在）  (exit=3)

# ⑥ 全部来源缺失（空 HOME + 无关 CWD + 仓库外的引导副本）→ 列出已尝试来源后报错
❌ 无法定位工作流根目录。已尝试：
  - Skill 开发源 / 脚本所在仓库 → C:\tmp（缺少必要文件：config/workflow.yaml；…）
  - 自当前目录向上探测：自 c:\tmp 向上 1 级均未通过校验
请任选其一后重试：…  (exit=3)
```

## 7. 兼容性

- Windows / Git Bash / Claude Code 任意 CWD：`_home.py` stdlib-only；MSYS 路径（`/d/...`）自动转换；
  安装记录以 `pwd -W` 写 Windows 原生路径
- 旧脚本行为兼容：`audit.py`/`notify.sh`/`jenkins_run.py` 解析失败时回退脚本自定位（历史行为）

## 8. 已知既有问题（非本次范围）

- `python -m pytest agent-manager` 收集失败：`from notifier import Notifier` 被
  `agent-manager/human_decision/notifier.py` 遮蔽（本次改动前即存在，未触碰）
- 并行会话文件（`scripts/project_resolver.py`、`scripts/repo_check.py`、
  `tests/test_project_resolver*.py`、`tests/test_repo_check.py`、`reports/PROJECT-REGISTRY-ANALYSIS.md`、
  `Readme.md`、`execution/hitl-*`）未纳入本次提交
