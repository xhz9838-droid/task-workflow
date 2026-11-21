# 工作流启动链路与多任务执行能力优化 — 审计与交付报告

- 日期：2026-11-21
- 源码根：`D:/WorkSpace/task-workflow`
- 范围：启动参数解析、多任务入口、`user_id` 依赖、统一预检、路径上下文复用
- 状态：源码开发 + 测试 + 实际验证完成；**未提交 Git、未打 Tag、未修改全局安装版本**
- 测试结果：`177 passed`（基线 140 + 本轮新增 37）

---

## 1. 现状审计

### 1.1 参数解析

| 事实 | 位置 |
|---|---|
| 唯一参数解析器是 `parse_invocation` | `scripts/_args.py:64`（改造前） |
| 多任务号直接抛错 `给定了多个任务号` | `scripts/_args.py:62`（改造前） |
| Skill 调用示例只写单任务 | `.claude/skills/zentao-dev-workflow/SKILL.md` 调用方式 |
| 下游没有任务列表消费方 | `preflight`（本轮新增）之前不存在；`dispatch.py` 只接受 `--task-id` |

结论：只有一处解析器，但**下游只支持单任务**，所以不能只改 `_args.py`。本轮同时补齐了
`preflight.py` 与 `dispatch.py batch-plan` 的任务列表消费链路。

### 1.2 用户身份依赖

| 调用点 | 原行为 | 真实用途 |
|---|---|---|
| `project_resolver.build_context` | `current_user_id()` 解析不到即抛 `ResolveError` | 仅用于 `config/users/{id}.yaml → project_paths` 仓库路径映射 |
| `_config.load_config` | `user_id` 显式传入且文件不存在 → `USER_CONFIG_NOT_FOUND` | 合并用户级配置 |
| `zt.py` | 禅道 API 认证走共享 `ZenTaoClient` 配置；归属校验用禅道 `whoami` | **与工作流 user_id 无关** |
| HITL | 决策人白名单来自 `config/adapters/hitl*.yaml` | **与工作流 user_id 无关** |

结论：`user_id` 只在“用户级仓库路径映射”和“用户级配置合并”时需要；禅道认证、任务查询、
回写、Agent 调度、HITL 决策人校验都不依赖它。原启动链路把可选项当成了必选项。

### 1.3 启动检查

| 检查 | 原状态 |
|---|---|
| 工作流根 | `scripts/_home.py` 统一解析，已完善 |
| 项目配置 | `scripts/_config.py`，错误码可区分 |
| 项目路径 | `project_resolver.repo_paths_for` + `repo_check.check_repo` |
| 仓库校验 | `scripts/repo_check.py` **只有模块函数，没有 CLI**：直接运行无输出、退出码恒为 0 |
| 统一预检 | 不存在；SKILL.md 用 6 条文字检查，重复执行且无统一结果 |

`repo_check.py` 的 `_git` 会把 Git 异常收进 `blocked` 明细（不抛出），模块调用方能看到；
但缺少 CLI 时人工直接运行确实“无输出、退出码无意义”。本轮补了 CLI。

### 1.4 多任务执行架构

- `dispatch.py`：单任务 DAG 调度，SQLite 为唯一真相源，`gate` 按任务终止。
- `Agent Manager`：按 execution 管理任务生命周期。
- 不存在跨任务编排器；也没有跨任务依赖数据来源。

结论：**不需要新建调度系统**。任务内 DAG、状态、门禁全部复用；只补一个只读的
`batch-plan` 计算跨任务依赖波次，执行仍由主控按任务走既有 `dispatch.py` 流程。

---

## 2. 修改清单

| 文件 | 类型 | 内容 |
|---|---|---|
| `scripts/_args.py` | 改 | 多任务号、`--tasks a,b,c`、`--tasks=a,b`、去重、`task_ids`/`duplicate_task_ids`；保留单任务 `task_id` |
| `scripts/project_resolver.py` | 改 | `build_context` 的 `user_id` 改为可选；新增 `resolve_user_id_optional`；`current_user_id`/`whoami` 保持严格 |
| `scripts/preflight.py` | 新增 | 统一启动预检：根/配置/上下文/仓库/任务参数/执行目录/可选任务详情/运行环境；PASS/WARN/BLOCKED + 动作；`--out` 落盘 |
| `scripts/repo_check.py` | 改 | 新增只读 CLI（`--project [--user] [--json]`），明确输出与退出码 |
| `scripts/dispatch.py` | 改 | 新增只读 `batch-plan`；`--task-ids`；`--depends`；`--parallel`；`--task-id` 改为主命令校验 |
| `.claude/skills/zentao-dev-workflow/SKILL.md` | 改 | 多任务调用、统一预检、多任务执行规则、user_id 可选 |
| `tests/test_args_multi.py` | 新增 | 14 项参数测试 |
| `tests/test_preflight.py` | 新增 | 13 项预检测试 |
| `tests/test_batch_plan.py` | 新增 | 10 项多任务计划测试 |

未改动：DAG 结构、Agent Manager、HITL、SQLite schema、Jenkins、业务仓库代码。

---

## 3. 参数兼容性

```text
/zentao-dev-workflow jeebootx 3442                  # 旧单任务：完全兼容
/zentao-dev-workflow jeebootx 3442 3443 3444 3445   # 多任务
/zentao-dev-workflow jeebootx --tasks 3442,3443     # 显式列表
/zentao-dev-workflow jeebootx --tasks=3442,3443     # = 形式
/zentao-dev-workflow jeebootx 3442 3442             # 去重（保留首次顺序，记录 duplicate_task_ids）
/zentao-dev-workflow #3415                          # 仅任务号：仍要求项目归属解析
```

- 多任务**不会**被合并成单个 `task_id`：`task_id` 仅在单任务时有值，多任务使用 `task_ids`。
- 非法任务号、两个不同 `project_key`、未知选项 → `ArgsError`，带正确用法。
- `dispatch.py`：单任务命令缺 `--task-id` 时仍在 `main()` 返回 2（与 argparse 必填行为一致），
  既有调用方式不变。

---

## 4. 多任务执行机制

`dispatch.py batch-plan`（只读）：

1. 读取每个任务已有的 `execution/{project}/{task}/tasks.yaml` 与 SQLite 节点状态；
2. 依赖来源：`tasks.yaml` 顶层 `depends_on_tasks`，或 CLI `--depends A:B,C:A`；
3. 循环依赖 → `DEP_CYCLE`；批次外未知依赖 → `DEP_UNKNOWN`（除非该任务已全部 DONE）；
4. 输出 `waves`、`execution_order`、每任务 `status/nodes/deps`；
5. **默认串行**（`parallel_within_wave=false`）；只有显式 `--parallel` 才允许同波次并行，
   避免“无法确认依赖时擅自假定并行”；
6. 不创建 execution、不登记派发、不改 run-state。

执行阶段由主控/Skill 按 `execution_order` 逐任务调用既有
`dispatch.py plan / register-dispatch / record-result / gate`；各任务状态、回写、验收独立。
一个任务失败或 `WAITING_HUMAN` 不影响其他独立任务（`batch-plan` 的 `attention`/`waiting_human`
状态不会进入其他任务的依赖判定）。

---

## 5. user_id 依赖调整

- 普通启动：`preflight` 解析不到 `user_id` → **WARN，继续**。
- `project_resolver.build_context`：`user_id` 可选；无用户时 `repo_paths` 回退项目配置 `repositories[].path`。
- `current_user_id()` / `whoami`：保持严格（显式诊断命令仍需明确身份）。
- 禅道 API、任务查询/回写：未改动，仍走共享 `ZenTaoClient` 配置。
- Human Decision：决策人白名单校验未改动，只在决策功能执行时生效。
- 显式传入不存在的用户配置：预检降级为无用户上下文并记录 WARN；不阻塞普通任务。

---

## 6. 统一预检

```bash
python -I scripts/preflight.py {project} {tasks...} [--tasks a,b] [--user id] \
    [--fetch-tasks] [--require-tasks] [--json] [--out file]
```

覆盖：工作流根、PyYAML、参数解析（与 Skill 同一解析器）、项目配置/上下文、用户（WARN）、
仓库（PASS/WARN/BLOCKED）、任务执行目录与 `tasks.yaml`、可选禅道任务详情、状态库、
禅道 Skill、HITL MCP。

- WARN：缺 user_id、工作区脏、首次执行无 DAG、任务详情获取失败（默认）；
- BLOCKED：工作流根无效、项目配置缺失、显式 user 下仓库路径不可用/Git 不一致、参数错误、
  `--require-tasks` 下任务详情失败；
- 退出码：0 无阻塞 / 1 有 BLOCKED / 2 参数用法错误；
- `--out` 写入 JSON，供后续阶段复用，避免重复检查。

---

## 7. 测试报告

命令：`python -I -m pytest -q`

| 范围 | 结果 |
|---|---|
| 全量 | **177 passed**（基线 140 + 新增 37） |
| `tests/test_args_multi.py` | 14 passed：单/双/四任务、`--tasks`、`=`、去重、非法号、缺项目、旧调用、CLI |
| `tests/test_preflight.py` | 13 passed：无 user、多任务透传、去重、非法参数、仓库缺失（有/无 user）、用户配置缺失降级、任务详情失败（WARN/BLOCKED）、多检查同时失败、context 无 user、退出码、repo_check CLI |
| `tests/test_batch_plan.py` | 10 passed：独立任务、声明依赖、CLI 依赖、循环、未知依赖、失败任务不阻塞、WAITING_HUMAN 不阻塞、DONE 状态、只读、参数透传 |

未覆盖（测试环境边界）：真实派发 Agent、真实 Jenkins、真实钉钉通知。

---

## 8. 实际验证记录（jeebootx，只读）

| 验证项 | 命令 | 结果 |
|---|---|---|
| 四任务预检（不传 user） | `preflight.py jeebootx 3442 3443 3444 3445 --json` | `ok=true`，PASS=9 WARN=8 BLOCKED=0 |
| 四任务详情 | 同上 + `--fetch-tasks` | `ok=true`，PASS=13 WARN=8 BLOCKED=0；4 个 `task_detail:*` 全 PASS，均 assigned_to=`xuhongzu`，status=`doing` |
| 显式列表 | `preflight.py --project jeebootx --tasks 3442,3443` | `ok=true`，task_ids 正确 |
| 多任务计划 | `dispatch.py --project jeebootx --task-ids 3442,3443,3444,3445 batch-plan` | rc=0；`waves=[[3442,3443,3444,3445]]`；`execution_order` 串行；errors=[] |
| 任务现状 | 同上 | 3442 `in_progress`（9 节点，A1 running）；3443/3444/3445 `not_started`（无 DAG） |
| 单任务兼容 | `dispatch.py --project jeebootx --task-id 3442 plan` | rc=0，输出既有结构 |
| 仓库校验 CLI | `repo_check.py --project jeebootx --json` | rc=0，4 个仓库 `ok`（脏工作区仅记录不阻断） |
| 非仓库目录启动 | 在 `D:/WorkSpace/jeebootx` 下运行 preflight | 工作流根 PASS，`ok=true` |
| 非法参数 | `preflight.py jeebootx abc --json` | rc=2，`ok=false`，给出“多个 project_key”原因 |

未执行：真实 Jenkins 构建/部署、真实任务派发（3442 的 A1 处于既有 running 状态，未触碰）。

---

## 9. 遗留问题与后续建议

1. **跨任务依赖只有显式声明**（`depends_on_tasks` / `--depends`）。禅道任务的 `story/execution`
   字段不足以可靠表达先后关系，因此不自动推断；未声明时保守串行。
2. 同波次并行需要主控显式传 `--parallel` 并真正并行启动多个任务；本轮未新增并行执行器。
3. 全局安装版本（`~/.claude/skills/zentao-dev-workflow/SKILL.md`）**未更新**，本轮按约束只改源码；
   交付后需执行 `scripts/install.sh` 同步。
4. `batch-plan` 对“有 DAG 但全部 DONE”的任务仍列入波次（`status=done`），执行方应跳过；
   后续可在输出中增加 `remaining` 列表。
5. 未提交 Git、未打 Tag、未发布。
