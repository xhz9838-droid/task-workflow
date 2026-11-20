# WORKFLOW 产品可交付性现状评估（Assessment）

- 盘点日期：2026-11-20
- 源码根：`D:/WorkSpace/task-workflow`（HEAD `e792ce3`，工作区含本次治理改动）
- 方法：只读静态盘点 + 真实运行验证 + 全量测试；不采信历史报告结论
- 说明：标注 **[已治理]** 的项已在本次实施阶段修复并有测试/运行证据；其余为待办或限制

---

## 1. 当前产品能力清单

| 能力域 | 能力 | 状态 |
|---|---|---|
| 项目接入 | `project_register.py` plan/apply 两段式 + 指纹确认 + 原子写 + 用户路径优先 | 可用 |
| 项目解析 | `project_resolver.py context/match/whoami`，身份解析 显式 > WORKFLOW_USER_ID > 用户 JSON | 可用 |
| 配置 | workflow → adapters → project → user → `.env` 深合并；`${VAR}` 展开 | 可用 |
| 任务获取 | 禅道适配器 `zt.py detail/project`；无适配器可从 task-context 手工输入 | 可用（真实只读已验证） |
| 需求/设计 | dw-architect 产出 design/ | 文档+Agent 定义齐备 |
| DAG 调度 | `dispatch.py plan/register/confirm/record/reconcile/export/status` | 可用；**本次新增 gate/flush-writes** |
| 状态持久化 | agent-manager SQLite（execution_runs / node_dispatches / pending_writes / events） | 可用 |
| 状态快照 | `run-state.json` 由 SQLite 导出 | 可用；**本次 record-result 自动刷新** |
| 决策分级 | L1/L2/L3 与 P0/P1/P2 | **[已治理]** 映射与禁降级 |
| 人工决策 | HITL：决策库/通知/回复解析/恢复/WAITING_HUMAN | 可用；本次补崩溃恢复与授权 |
| 通知 | 钉钉直发 + cc-connect 兜底；`notify.sh` | **[已治理]** set -e 中断/审计丢失/project_key |
| 验收 | Verifier 五态 + git 证据 | 可用但证据面窄（见 §4） |
| 重试 | retry 分类/上限/指数退避（CLI 路径） | 可用；DAG 层本次补预算阻塞 |
| 禅道回写 | progress 追加幂等 / finish / close / 读回 / pending_writes | 可用；**本次新增 flush 入口并统一策略配置** |
| Jenkins | toolcheck / 白名单 / 非 SUCCESS 不判通过 | 真实连通已验证，未触发构建 |
| 安装 | `install.sh` 安装 Skill+Agents+注册 Skill+记录+用户配置；`--with-mcp` | **[已治理]** |
| 诊断 | `doctor.py` 版本/根/配置/依赖/DB/安装/MCP | **[已治理]** |
| 版本 | `VERSION`（0.9.0）+ requirements.txt | **[已治理]**；无 tag/CHANGELOG |

---

## 2. 已完成且有测试证据的功能

| 功能 | 测试/证据 |
|---|---|
| 用户身份解析（禁止 OS 用户名） | `tests/test_project_resolver_user.py`（20 项含 CLI 生命周期，全过） |
| SQLite schema 初始化/迁移/幂等/回滚/拒绝降级/备份 | `tests/test_db_migration.py` |
| 禅道 finish/close 幂等、读回、配置拒绝 | `tests/test_zt_finish_close.py` |
| CLI 参数/退出码/dry-run/锁/JSON | `agent-manager/tests/test_cli.py`（本次新增 check 结果断言） |
| 路由/重试/Verifier/通知/Jenkins/状态恢复 | `agent-manager/tests/test_integration.py`（本次新增 check 结果断言） |
| HITL 决策生命周期/回复解析/超时/恢复/通知失败不放行 | `agent-manager/human_decision/tests/*`（64 项全过） |
| DAG 状态语义（WAITING_HUMAN/UNVERIFIED/重试预算/门禁/快照） | `tests/test_dispatch_state.py`（8 项，本次新增） |
| 配置错误码/脱敏/Windows 注册参数 | `tests/test_config_diagnostics.py`（8 项，本次新增） |
| L3 分级/崩溃恢复/CLI 授权 | `human_decision/tests/test_hardening.py`（7 项，本次新增） |
| #3438 场景 A/B 回归 | `human_decision/tests/test_route_3438.py`（2 项，本次新增） |
| 全量 | `bash scripts/run_tests.sh` → **140 passed**（2026-11-20） |

---

## 3. 尚未实现的功能

1. **DAG 自动调度器**：`plan` 只输出可执行集合，必须主控逐节点派发；无后台循环。
2. **统一 resume 命令**：恢复依赖 Skill 文档 + `plan/reconcile`，无单一 `resume` 入口。
3. **任务级状态机校验**：`update_execution` 接受任意 `workflow_status`，无转换表。
4. **真实测试自动执行**：CLI Verifier 不传 test_specs/requirement_checks，实际只跑 Git。
5. **跨平台验证**：仅 Windows 实测；macOS/Linux 未验证。
6. **CHANGELOG/自动回滚**：无 tag、无发行构建脚本、无自动回滚命令。
7. **部署 Job 人工确认 UI**：仅靠白名单 + 策略禁止自动触发。

---

## 4. 已实现但不可靠的功能（未在本轮全部修复）

| 项 | 问题 | 影响 | 证据 |
|---|---|---|---|
| Verifier 完成判定 | 未传测试规格，`require_commit` 语义名不副实；`overall=PARTIAL` 仍视为 passed | 可能仅凭 Git 证据自动 finish | `agent-manager/cli.py` `_cmd_run`；`models.py` `passed()`；`verifier.py` |
| 任务级状态 | dispatch 不更新 `execution_runs`（除本次 `gate --finalize`） | 节点全 DONE 时任务可能仍 PENDING，需显式 finalize | `scripts/dispatch.py` |
| RESUMED 语义 | `SessionResumer.resume` 按启发式选路后即记 RESUMED，live 注入不验证送达 | 报告可能声称“已恢复”但实际未注入 | `human_decision/session_resumer.py` |
| 通知失败补发 | 运行中不补发，仅 `recover()` 补发 | 通知失败需 daemon 重启/手动 recover | `decision_manager.poll_once`；`recovery_handler` |
| 决策与 execution 关联 | `execution_id` 列从未写入 | 同任务多 execution 时歧义 | `human_decision/decision_store.py` |
| 迁移信任 | 旧 `done` 无条件迁 DONE | 历史错误完成态可能被洗白 | `scripts/migrate_runstate.py` |
| 配置双写 | `agent-manager/config.yaml` 的 zentao 策略不被 zt.py 使用 | 两处配置可能漂移 | 本次已将 `config/adapters/zentao.yaml` 对齐为 auto_after_gate |
| 路径解析写副作用 | `plan/status/gate` 在无 execution 时会创建空壳 | 只读命令产生写入 | `dispatch._resolve_execution_id` |

---

## 5. 产品交付阻塞问题（盘点时 → 本轮处置）

| # | 阻塞 | 处置 |
|---|---|---|
| B1 | `dispatch plan` 将 WAITING_HUMAN 节点同时列为 blocked 和 executable | **已修复** + 回归测试 |
| B2 | UNVERIFIED/FAILED 可被 plan 自动重派，无重试预算 | **已修复** + 测试 |
| B3 | L1/L2/L3 与 P0/P1/P2 无映射；显式等级可降级 P0；传 L3 抛异常 | **已修复**（normalize + 禁降级 + 路由策略） |
| B4 | L2 普通设计可被塞进 HITL（默认 A3 人工确认） | **已修复**（模板 A3 改为 L2 自动/L3 人工；显式 L1/L2/P2 创建决策直接拒绝） |
| B5 | 崩溃残留在 DECISION_RECEIVED/RESUMING/RESUME_FAILED 永久卡住 | **已修复**（recover 回收）+ 测试 |
| B6 | CLI 回复空 `user_id` 可绕过决策人白名单 | **已修复** + 测试 |
| B7 | `scripts/_config.py show` 脱敏为空操作（凭据泄露） | **已修复**（递归脱敏 + URL userinfo）+ 测试 |
| B8 | `project_register --repo` 在 Windows 盘符/HTTPS 远程 URL 解析错误；`--out` 父目录不创建 | **已修复** + 测试 |
| B9 | 安装不装注册 Skill；已安装 SKILL 引用不存在的 `register_from_task.py`；Skill 自举路径错误 | **已修复**（install.sh 装注册 Skill；SKILL 第 0 步显式读取 `.home`；重新安装并验证一致） |
| B10 | `notify.sh` 在 `set -e` 下发送失败即退出，审计/清理不执行；缺 project_key | **已修复** |
| B11 | 无版本、无诊断入口 | **已治理**（VERSION + doctor + requirements.txt） |

---

## 6. 非阻塞问题（保留）

1. 适配器在 `load_config` 中以文件名为 key 包裹（`hitl` / `hitl.local`），语义混乱（HITL 实际直接读文件，暂不影响）。
2. `install.sh` 无 Skill 目录备份（升级为整目录替换）；卸载仅删除软链别名（本次已收紧）。
3. `agent-manager/tests` 依赖文件内 `sys.path` 顺序；已通过 conftest 顺序修正使一次性运行可用。
4. `_config.py validate` 的集成↔适配器检查仍有启发式映射。
5. `release_run.py` 的 execution 根已改为工作流根解析，但缺少测试。
6. 无 PyYAML 以外的依赖清单；已补 `requirements.txt`。
7. 已跟踪的本地配置（`config/projects/*.yaml` 等）绕过 `.gitignore`；当前不含真实凭据，建议后续 `git rm --cached`。

---

## 7. 安全与数据风险

| 风险 | 状态 |
|---|---|
| `show` 泄露 token/secret | **已修复**（键名命中即 `***`；URL 内嵌凭据掩码） |
| 日志/通知/DB 写凭据 | 未发现；HITL 通读未发现 token 落盘 |
| CLI 空身份绕过白名单 | **已修复** |
| HTTP hook 无鉴权 | 仅绑 127.0.0.1（本机信任边界）；改绑 0.0.0.0 有风险（未改） |
| DB 明文业务内容 | 无保留期/脱敏策略（未改） |
| `.env`/execution/token 未入库 | 已 gitignore；已验证 |

---

## 8. 测试覆盖情况

- 总测试：**140 passed**（2026-11-20，`scripts/run_tests.sh`）。
- 一次运行全部套件的同名模块冲突已修复（conftest 路径顺序）。
- 自定义 `check()` 测试在 pytest 下不再“假绿”（新增汇总断言）。
- **缺口**：真实钉钉投递、真实 MCP 阻塞等待端到端、真实 Jenkins 构建、会话级 `--resume`、macOS/Linux。

---

## 9. 建议实施顺序

1. （已完成）DAG/门禁/HITL 分级与恢复/配置安全/安装自举。
2. 收紧 Verifier：CLI 必须传入测试规格/需求项，`PARTIAL` 不触发自动 finish。
3. 任务级状态转换校验 + dispatch 自动同步 execution 状态。
4. 通知失败运行中补发 + 决策 `execution_id` 关联。
5. 发布工程：tag、CHANGELOG、发行构建/回滚脚本、发行仓库单向同步。
6. 跨平台 CI 与真实环境回归。

---

## 10. 结论对应证据索引

| 结论 | 证据 |
|---|---|
| 全部测试通过 | `scripts/run_tests.sh` 输出 `140 passed` |
| 门禁可用 | `dispatch.py --project jeebootx --task-id 3438 gate` → `ok:true`（7 节点全 done） |
| 快照与真相源一致 | `record-result` 输出含 `run_state`；测试断言 `state_source=sqlite` |
| 安装一致 | `diff ~/.claude/skills/zentao-dev-workflow/SKILL.md .claude/skills/.../SKILL.md` → SAME |
| 任意目录运行 | 在 `D:/WorkSpace` 用 `.home` 解析 + `doctor.py` → 结论 OK |
| 配置校验 | `_config.py validate jeebootx xuhongzu` → 通过 |
| 真实禅道 | `zt.py detail --task 3438` → 返回真实任务（status=done） |
| 真实 Jenkins | `jenkins_run.py toolcheck` → 连接/认证/白名单/CSRF 全部 ✅，未触发构建 |
| MCP 用户级 | `claude mcp get human-decision`（/tmp）→ User config + Connected |
| 场景 A/B | `test_route_3438.py` 2 passed |
