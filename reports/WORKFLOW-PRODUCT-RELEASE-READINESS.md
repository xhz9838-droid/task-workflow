# WORKFLOW 产品交付验收报告（Release Readiness）

- 产品：zentao-dev-workflow
- 版本：`0.9.0`（`VERSION`）
- 源码 Commit：`e792ce3`（本治理改动尚未提交，工作区 +23 文件）
- 验收日期：2026-11-20
- 验收环境：Windows 11 / Python 3.13.1 / PyYAML 6.x / Claude Code CLI

---

## 1. 版本与源码

| 项 | 值 |
|---|---|
| 源码根 | `D:/WorkSpace/task-workflow`（唯一开发源） |
| HEAD | `e792ce3` |
| 产品版本 | 0.9.0（新增 `VERSION`） |
| 依赖清单 | 新增 `requirements.txt`（PyYAML>=6.0） |
| 安装记录 | `~/.claude/zentao-dev-workflow.home` → `D:/WorkSpace/task-workflow` |
| 用户配置 | `~/.claude/zentao-dev-workflow.json` → `workflow_home`（保留已有字段） |
| 发行仓库 | `lianzhu-skills`（本次未同步，无 push 授权） |

---

## 2. 本次完成的改动

### P0 核心执行可靠性
- `scripts/dispatch.py`
  - `plan`：WAITING_HUMAN 不再进入 executable；UNVERIFIED 必须人工确认；FAILED/RETRY_PENDING 受 `retry.max_attempts` 预算约束；重试耗尽进 blocked；决策完成后（execution 非 WAITING_HUMAN）允许恢复派发。
  - `register-dispatch`：新增 `--force-new-attempt`；UNVERIFIED/仍等待人工的 WAITING_HUMAN 拒绝无确认重派。
  - `record-result`：自动刷新 `run-state.json` 快照（失败仅告警，不影响已记录结果）。
  - 新增 `gate [--finalize]`：统一终止门禁（全节点 DONE、无 WAITING_HUMAN、无 live Agent、pending_writes=0）；`--finalize` 置 COMPLETED。
  - 新增 `flush-writes`：重试 `pending_writes`（禅道 progress/finish/close）。
- `scripts/notify.sh`：发送失败不再中止脚本；审计与清理始终执行；消息补 `project_key`；缺参/缺 session 文件安全降级。

### P0 决策路由与 HITL
- `human_decision/models.py`：`DecisionLevel.normalize()`（L3→P0 / L2→P1 / L1→P2）+ `severity`。
- `human_decision/decision_detector.py`：显式等级与关键词检测取较高级别，**禁止显式降级 P0**；接受 L1/L2/L3 输入。
- `human_decision/routing.py`（新增）：`route_decision` 明确 auto/hitl 与 ADR 记录要求。
- `human_decision/decision_manager.py`：显式 L1/L2/P2 创建决策 → 拒绝（应在授权内自决并写 decisions.md）。
- `human_decision/recovery_handler.py`：回收 `DECISION_RECEIVED / RESUMING / RESUME_FAILED` 崩溃残留。
- `human_decision/reply_handler.py`：配置决策人白名单后，CLI 空 `user_id` 不得通过身份校验。
- 模板/文档：DAG 模板 A3 改为“L2 自动 / L3 人工”；SKILL 与 approval-policy 统一 MCP 路由；删除“对话直接询问”兜底。

### P1 安装、配置、诊断
- `scripts/_config.py`：可区分错误码（PROJECT/USER/ENV/PARSE/MERGE）；`${VAR}` 报错带具体文件；`show` 真脱敏（嵌套键 + URL 内嵌凭据）；`validate` 支持用户 `project_paths` 与发行布局 Agent 目录。
- `scripts/project_register.py`：`--repo` 兼容 Windows 盘符与 `https://` 远程地址；`--out` 自动创建父目录；删除不存在的 `update` 模式提示。
- `scripts/zt.py`：缺少禅道 Skill 依赖时给出可操作错误而非 traceback。
- `scripts/install.sh`：安装 `workflow-register-project`；写/合并用户级 `workflow_home`；`--with-mcp` 注册 HITL MCP；卸载不误删用户同名 Skill；移除死代码。
- `scripts/doctor.py`（新增）：版本/工作流根/来源/Python/PyYAML/项目/用户/适配器/.env 键名/DB schema/安装/MCP，不输出凭据值。
- `scripts/release_run.py`：execution 根改用工作流根解析。
- `.claude/skills/zentao-dev-workflow/SKILL.md`：第 0 步显式读取安装记录（禁止猜 Skill 目录）；未注册项目就地注册；结束门禁命令。
- `Readme.md`：同步目录/安装/测试/诊断/注册命令；删除不存在的脚本与测试引用。

### 配置策略
- `config/adapters/zentao.yaml`：`allow_finish/allow_close` 改为 `auto_after_gate`，与 CLAUDE.md/SKILL 一致（zt.py 仍校验前置条件与读回）。

---

## 3. 核心能力验收表

| 能力 | 验收项 | 结果 | 证据 |
|---|---|---|---|
| 工作流生命周期 | 状态持久化、恢复、重复执行无重复副作用 | ✅ | SQLite `node_dispatches` + `run-state` 快照测试；迟到通知测试 |
| DAG 调度 | 依赖满足、并行独立节点、幂等 | ✅ | `test_dispatch_state.py`；`dispatch plan` 真实任务 |
| 终止门禁 | 未完成/待人工/待回写/存活 Agent 不得结束 | ✅ | `dispatch gate` 测试 3 项（含 finalize） |
| L1/L2 | 自决 + decisions.md，不调用 HITL | ✅ | `test_route_3438.py::scenario_a`；`route_decision` |
| L3 | 创建决策、WAITING_HUMAN、通知、阻塞依赖、完成后恢复 | ✅（模拟通知） | `test_route_3438.py::scenario_b`；`test_task_state_hook` |
| 崩溃恢复 | DECISION_RECEIVED/RESUMING/RESUME_FAILED 可回收 | ✅ | `test_hardening.py` 3 项 |
| 通知失败 | 记为 NOTIFY_FAILED，不放行 | ✅ | `test_notify_failure_keeps_decision_waiting` |
| 禅道回写 | 追加幂等/finish/close/读回/失败入队 | ✅ | `test_zt_finish_close.py`；`flush-writes` 入口 |
| Verifier | 未通过不得 finish | ✅（但证据面窄，见 §7） | `test_cli_lifecycle.py` / `test_integration.py` |
| 安装独立 | 不依赖开发目录、Skill 自举、配置不覆盖 | ✅ | 非仓库目录运行 doctor/validate；SKILL diff SAME |
| 版本与诊断 | 版本号、doctor、依赖清单 | ✅ | `VERSION`、`requirements.txt`、`doctor.py` |
| 配置诊断 | 错误码、脱敏、Windows 路径 | ✅ | `test_config_diagnostics.py` 8 项 |
| Jenkins 边界 | 只允许白名单、部署禁自动 | ✅（策略） | `toolcheck` 真实连接；未触发构建 |

---

## 4. 测试执行结果

```
$ bash scripts/run_tests.sh
140 passed, 1 warning in 8.49s
```

- 覆盖：编排层（dispatch/CLI 生命周期/DB 迁移/禅道 finish-close/config/身份）、agent-manager（CLI/集成）、HITL（存储/管理/回复/恢复/任务桥/加固/路由）。
- 警告 1 项：`TestSpec` 被 pytest 误收集（类名以 Test 开头），非失败。
- 无跳过测试、无降低断言；本次还修复了自定义 `check()` 在 pytest 下的“假绿”。

---

## 5. 真实环境验证结果

| 项 | 结果 | 命令/证据 |
|---|---|---|
| 禅道只读 | ✅ | `zt.py detail --task 3438` → 真实任务（status=done，负责人 xuhongzu） |
| 禅道任务状态 | ✅ | 3438 已在 done；本次未重复流转 |
| Jenkins 连接/认证/白名单/CSRF | ✅ | `jenkins_run.py toolcheck`（4 项 ✅，未触发构建） |
| 工作流根解析（任意目录） | ✅ | 在 `D:/WorkSpace` 读取 `.home` → `_home.py` 输出根 |
| 配置加载/校验 | ✅ | `_config.py validate jeebootx xuhongzu` 通过 |
| HITL MCP（user scope） | ✅ | `claude mcp get human-decision`（/tmp）→ Connected |
| 钉钉消息实发 | ⏸ 未执行 | 避免对外发送；由 FakeNotifier 集成测试覆盖 |
| 真实 L3 决策端到端 | ⏸ 未执行 | 同上；场景 B 已用真实 DecisionManager+Hook+StateManager 验证 |
| Jenkins 真实构建 | ⏸ 未执行 | 任务 3438 构建 #167 历史 SUCCESS，本轮不重复触发 |
| 会话级 `--resume` | ⏸ 未执行 | 恢复逻辑单元测试通过；真实 cc-connect 恢复未验证 |

---

## 6. 安装与升级验证

| 项 | 结果 |
|---|---|
| 从源码安装 | ✅ `bash scripts/install.sh` 成功安装主体 Skill、注册 Skill、7 个 Agent |
| 安装后 Skill 与源码一致 | ✅ `diff` → SAME |
| 安装记录/用户配置 | ✅ `.home` 与 `~/.claude/zentao-dev-workflow.json` 写入 |
| 升级不覆盖数据 | ✅ 未触碰 `config/`、`execution/`、`.env`、SQLite |
| 旧安装备份 | ✅ `~/.claude/zentao-dev-workflow.bak.20261120130319`（移出 skills 目录） |
| 卸载安全性 | 代码已收紧（只删软链别名）；未实际卸载验证 |
| 回滚 | 手动：恢复备份目录 + 重跑旧源码 `install.sh`；无自动回滚命令 |

---

## 7. 已知问题（发布后需优先处理）

| # | 级别 | 问题 | 影响 |
|---|---|---|---|
| K1 | HIGH | CLI Verifier 未传测试规格/需求项，实际只验 Git；`PARTIAL` 仍视为 passed | 弱证据也可能自动 finish；建议强制 `test_specs` 且 PARTIAL 不得 finish |
| K2 | MEDIUM | dispatch 不自动同步任务级状态（仅 `gate --finalize`） | 需主控显式 finalize；否则 execution 可能停留 PENDING |
| K3 | MEDIUM | `RESUMED` 表示“选路完成”而非“会话已恢复”；注入不验证送达 | 恢复结果可能被高估 |
| K4 | MEDIUM | 通知失败运行中不补发（仅 recover 补发） | 需 daemon 重启/手动 recover |
| K5 | MEDIUM | 决策 `execution_id` 未写入 | 同任务多次 execution 关联歧义 |
| K6 | LOW | `plan/status/gate` 对无 execution 任务有建空壳副作用 | 只读命令写库 |
| K7 | LOW | 迁移脚本无条件信任 legacy done | 历史错误完成态可能被洗白 |
| K8 | LOW | 已跟踪的本地配置绕过 .gitignore | 当前无凭据，建议 `git rm --cached` |

---

## 8. 未完成事项

1. Git 提交、tag（`v0.9.0`）、CHANGELOG 未创建（未获提交授权）。
2. 发行仓库 `lianzhu-skills` 单向同步未执行。
3. 真实钉钉通知、真实 MCP 阻塞等待、会话恢复、Jenkins 构建未做外部验证。
4. macOS/Linux 未验证。
5. 自动回滚脚本、发行构建脚本未实现。

---

## 9. 风险与限制

- 本产品为 **run-in-place（整仓就地运行）**：Skill 只含文档，`scripts/config/agent-manager/.env` 必须在工作流根；通过安装记录/用户配置定位。纯“只装 Skill”无法运行。
- 决策/通知内容明文存 SQLite，无保留期策略；敏感业务信息不应写入决策问题。
- Jenkins 部署 Job 一律不自动触发；构建仍可能产生真实副作用（本报告未触发）。
- 禅道 finish/close 已在配置层允许自动执行（gate 通过/条件满足），但本报告未执行任何真实状态流转。

---

## 10. 发布建议

**READY_WITH_LIMITATIONS**

核心执行链路、决策路由、崩溃恢复、安装自举、配置安全与诊断已达到可交付水平，测试全绿并有真实禅道/Jenkins/安装环境证据；但 Verifier 证据面（K1）是明确的质量门禁弱点，必须在下一版本优先收紧。发布时应同时披露 K1/K2/K3 与“run-in-place”约束。

---

## 11. 发布步骤

1. 在源码仓库提交本次改动并打 tag：`git tag -a v0.9.0 -m "product readiness governance"`（需用户授权）。
2. 更新 CHANGELOG（按 §2 摘要）。
3. 单向同步到发行仓库 `lianzhu-skills/zentao-dev-workflow`（scripts/agent-manager/skill/agents/config 模板），
   不携带 `.env`、`execution/`、真实配置与 token。
4. 在发行仓库提交并打发行 tag（`zentao-dev-workflow/v0.9.0`）。
5. 用户机器升级：`cd <运行时根> && bash scripts/install.sh --with-mcp`。
6. 验证：`python -I scripts/doctor.py --project <key> --user <id>` → OK；`bash scripts/run_tests.sh` → 140 passed。
7. 核对 `~/.claude/skills/zentao-dev-workflow/SKILL.md` 与源码一致。

---

## 12. 回滚步骤

1. 恢复 Skill：`rm -rf ~/.claude/skills/zentao-dev-workflow && mv ~/.claude/zentao-dev-workflow.bak.<ts> ~/.claude/skills/zentao-dev-workflow`。
2. 回滚源码：`git checkout <上一稳定提交>`（无 tag 时按提交号）。
3. 重跑旧源码 `bash scripts/install.sh`。
4. 数据无需回滚：本次未修改 `execution/`、SQLite schema（仍为 v1）、`.env` 与业务仓库。
5. 如已同步发行仓库：在发行仓库 `git revert` 对应提交并重装。

---

## 附：本轮验证命令清单

```bash
bash scripts/run_tests.sh
python -I scripts/doctor.py --project jeebootx --user xuhongzu
python -I scripts/_config.py validate jeebootx xuhongzu
python -I scripts/dispatch.py --project jeebootx --task-id 3438 plan
python -I scripts/dispatch.py --project jeebootx --task-id 3438 gate
python -I scripts/zt.py detail --task 3438
python -I scripts/jenkins_run.py toolcheck
bash scripts/install.sh
claude mcp get human-decision        # 在非仓库目录执行
```
