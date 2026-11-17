# 项目注册与自动发现机制 — 验收报告（P07）

> 2026-11-17 · 对照任务 §十 验收标准 15 项 · 测试基线 177 PASS / 0 FAIL

## 验收标准逐条核验

| # | 标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | 新项目可通过 /workflow-register-project 注册 | ✅ PASS | Skill 已注册（12 步引导）+ `project_register.py` plan/apply；tmp 全链路注册测试 13 项全绿 |
| 2 | 项目公共配置与个人路径配置分离 | ✅ PASS | 注册产物分离实测：项目配置**无** path 字段，个人路径仅入 `config/users/{id}.yaml`（test_register_new_project_ok） |
| 3 | 一个 ZenTao 项目可关联多个代码仓库 | ✅ PASS | 多仓库测试（backend+frontend）+ 真实 jeebootx 4 仓库配置上下文构建成功 |
| 4 | 不同用户可配置同一项目的不同本地路径 | ✅ PASS | test_two_users_see_different_paths / test_different_users_different_paths |
| 5 | 只输入禅道任务 ID 可唯一识别项目 | ✅ PASS | `zt.py project` + `resolver.match`：project_id 精确/product 辅助唯一命中→resolved（含真实只读冒烟） |
| 6 | 无法唯一识别时安全阻断并询问用户 | ✅ PASS | ambiguous/needs_confirm/unregistered 三态 + SKILL 流程强制询问；名称命中**不自动采用**（test_name_only_match_needs_confirm） |
| 7 | 任意目录启动正常 | ✅ PASS | 31 交付 _home 解析（43 项）+ 本任务 test_registry_loadable_from_any_cwd + 真实 context 冒烟 |
| 8 | 多项目执行状态隔离 | ✅ PASS | exec_root 按 project_key 隔离 + test_execution_roots_isolated_per_project / test_two_projects_same_task_isolated |
| 9 | 原有 jeebootx 项目配置兼容 | ✅ PASS | 真实环境 `context --project jeebootx` 成功 + `validate` 通过（零改动） |
| 10 | 原有 demo-react 配置兼容 | ✅ PASS | 真实环境 `context --project demo-react` 成功（api/ui 双仓库路径解析）+ `validate` 通过 |
| 11 | 原有 HITL 测试通过 | ✅ PASS | human_decision/tests 56 passed |
| 12 | 原有 Agent Manager 测试通过 | ✅ PASS | agent-manager/tests 20 passed |
| 13 | 项目注册测试和解析测试全部通过 | ✅ PASS | 新增 58 项（注册 13/解析 15/仓库 18/zt 4/集成 7）全绿；总 177 PASS / 0 FAIL |
| 14 | 配置、凭据、Git 工作区安全检查通过 | ✅ PASS | 新增文件凭据扫描 CLEAN；注册仅写两处配置且拒绝覆盖（测试证实）；禅道只读；Git 只读；未动 execution 历史与并行会话文件 |
| 15 | 文档完整（注册/使用/故障排查/配置规范） | ✅ PASS | `docs/project-registry.md`（7 节）+ `/workflow-register-project` SKILL.md（含故障排查表）+ 本报告三件套 |

**结论：15 / 15 PASS。** 机制验收通过；真实项目注册演示与工作流级 E2E 按用户决定归入"真实任务全流程"阶段（见实施报告 §十二）。

## 安全红线复核（任务 §十二 14 条）

| 红线 | 结果 |
|---|---|
| 不覆盖现有用户配置 | ✅ 拒绝覆盖测试证实（test_no_overwrite_existing_user_mapping） |
| 不覆盖并行 Agent 未提交文件 | ✅ 提交路径限定；31 会话文件交接清晰（0d6e8a7 前等待其提交） |
| 不修改/删除 execution 历史 | ✅ 未触碰 |
| 不泄露凭据 | ✅ 扫描 CLEAN；token 缓存已 .gitignore 防护 |
| 不自动 clone/checkout/切分支/改 remote | ✅ repo_check 仅只读 git 命令 |
| 不自动 Git Push | ✅ 未 push |
| 不自动部署/重启服务 | ✅ 未执行 |
| 不执行 task_finish/task_close | ✅ 禅道仅 projects/project/detail 只读 |
| 不擅自禅道写操作 | ✅ 同上 |
| 注册失败不产生不完整配置 | ✅ 原子写 + 校验前置（fail 不写） |
| 识别失败不猜测代码目录 | ✅ 无命中即 unregistered，零创建 |
| 保留 HITL 人工审批 | ✅ 未改动 |
| L3 走人工决策闭环 | ✅ 注册确认环节即人工审批点 |
| 注册不绕过权限/审批 | ✅ 本人任务校验（whoami）+ 用户确认指纹 |

## 并行协作记录

- **task-workflow-31**（任意目录启动）：分工书面协调，互不覆盖；其 `match_project`/`_args.parse_invocation`/`_home` 接口被本任务复用（匹配谓词单点）；其提交 0d6e8a7 后本任务方增量改共享文件。
- **task-workflow-a9**（HITL daemon/resume）：前序验收阶段已交接（87d02b4/927083e）。
- 工作区他人产物（Readme.md、execution/jeebootx/3415/ 运行态）均未纳入本次提交。

## Git Commit

- 实现提交：`f2daa5f`（feat: 项目注册与自动发现机制；含 scripts/、tests/、docs/、skills/、config 模板、分析与实施报告）
- 本验收报告所在提交：紧随其后的 chore/docs 提交（见 `git log --oneline -2`）
- 前置协作提交：`0d6e8a7`（task-workflow-31：WORKFLOW_HOME 任意目录启动，本任务复用其 _home/_args/match_project）
- 未推送远程（按要求）。
