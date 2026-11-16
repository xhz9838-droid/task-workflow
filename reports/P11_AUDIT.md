# P11 Phase 0 现状审计

> 2026-11-16 · Main Agent 直接审计（未启动 Explore Agent，遵守执行纪律 #2）

## 一、Git 现状

- 分支：`main`
- 提交历史（5 个 P01-P10 提交）：`63b12bc` → `717de4c` → `f0cac96` → `6db2eac` → `9a4b168` → `ee08e5c` → `8d11874`
- `8d11874` = P01-P10 通用化升级，未重写
- 工作区未提交：`execution/jeebootx/3413/`（run-state/session/audit/qa-report/decisions）—— 是 3413 运行产物，**不覆盖**

## 二、可复用模块（P01-P10 资产）

| 模块 | 位置 | 行数 | P11 复用方式 |
|---|---|---|---|
| 配置加载器 | `scripts/_config.py` | 290 | **直接 import**，6 层加载 + 环境变量替换 |
| Jenkins 适配器 | `scripts/jenkins_run.py` | 775 | **直接 import**，已有 `WHITELIST`/`_verify_whitelist`/`cmd_trigger`/`cmd_status`/`cmd_report` |
| ZenTao 适配器 | `scripts/zt.py` | 117 | **直接 import**，已有 `detail`/`progress`（PUT + 读回核验） |
| 通知适配器 | `scripts/notify.sh` | 39 | CC Connect CLI 封装（`cc-connect send --stdin`） |
| 审计 | `scripts/audit.py` | 45 | **直接 import**，`audit(task_id, action, detail, project_key)` |
| Skill | `.claude/skills/zentao-dev-workflow/` | SKILL.md + 6 refs + 4 templates | 增量改（加 Task Classification 等规范） |
| Subagents | `.claude/agents/dw-*.md` | 7 个 | 保留，加 Dispatch Policy 约束 |
| 配置层 | `config/` | 14 文件 | 增 `agent-manager/config.yaml` |

**关键**：ZenTao Client、认证、Python 工具链、项目映射、配置加载、状态隔离、Skill、CC Connect、Git Worktree —— 全部复用，**不新建第二套**。

## 三、缺少的功能（P11 需新增）

| # | 缺口 | 对应模块 |
|---|---|---|
| 1 | 任务智能分级 S/M/L | `task_router.py` |
| 2 | Agent 生命周期管理（启动/监控/取消/超时） | `runner.py` + `monitor.py` |
| 3 | Agent 状态机 | `models.py` |
| 4 | 有限重试 + 故障分类 | `retry.py` |
| 5 | 结果验证门禁（PASS/FAIL/BLOCKED/SKIPPED/NOT_RUN） | `verifier.py` |
| 6 | SQLite 状态持久化 + 断点恢复 | `state_manager.py` |
| 7 | 禅道回写（复用 zt.py） | `zentao_reporter.py` |
| 8 | 事件通知（复用 notify.sh/CC Connect） | `notifier.py` |
| 9 | 任务级锁（防重复启动） | `state_manager.py` |
| 10 | 执行统计（Agent 数/耗时/工具调用） | `runner.py` + `models.py` |

## 四、环境能力确认

| 项 | 状态 |
|---|---|
| Python | 3.13.1（`python` 命令，`python -I` 隔离可用） |
| sqlite3 | ✅ 3.45.3（标准库，可用于状态持久化） |
| CC Connect | ✅ v1.5.0，`cc-connect send` CLI 可用 |
| Windows | Win11 + Git Bash，需 UTF-8 处理 |
| Jenkins | 2.555.2，白名单 `ai-test-*`（`_load_whitelist()` 从配置读） |
| ZenTao | `xuhongzu` 身份已核验 |

## 五、可能冲突的文件（P11 不得破坏）

| 文件 | 状态 | 处理 |
|---|---|---|
| `execution/jeebootx/3413/*` | 未提交运行产物 | 只读引用，不改写 |
| `execution/3413/*` | 历史副本 | 不动 |
| `docs/3413/*` | W1/QA1 设计与验收 | 不动 |
| `.worktrees/jeebootx-ui-zt3413` | W1 commit `1c302d6` | 不动 |
| `scripts/jenkins_run.py_a` | 用户备份 | 不动 |
| `scripts/start-claude.sh` | 用户脚本 | 不动 |
| 业务仓库脏文件 | sanitation 4 / upms 1 / app 1 | 不动 |

## 六、当前任务 3413 状态（效率问题实证）

```
A1-A2: done        设计
A3:   done        设计确认
W1:   done_partial_verified   commit 1c302d6
QA1:  done         7 pass / 12 BLOCKED，21 分钟
IR1:  ready        已被用户停止
CI:   pending
FINAL: pending
```

**实测效率问题**（P11 要解决的）：
- QA1 耗时 21 分钟，其中 `npm run build` 占 6m49s（用户已说跳过）
- 12 条 BLOCKED 全是本地环境无法验证的（浏览器/后端/DB）
- 子 Agent 重复读取主 Agent 已有的上下文（需求/架构/验收矩阵/代码）
- **本任务实为 S 级**（单文件 105 行纯前端），却跑了 3 Explore + W1 + QA + IR 全流程

## 七、实施风险

| 风险 | 缓解 |
|---|---|
| 破坏 P01-P10 | 只增文件；Skill/Agent 增量改；不改 `scripts/` 现有函数签名 |
| Windows 进程/编码 | `subprocess` 用 `creationflags=CREATE_NEW_PROCESS_GROUP`；强制 UTF-8 |
| PID 重用误判 | 恢复时核对进程启动时间 + 工作目录 |
| 伪造心跳 | 无可靠心跳源 → 只做外部进程监控，标 `heartbeat=unavailable` |
| 误杀思考中的 Agent | `output_idle` 只告警不杀；超时按**阶段**判断 |
| 重复执行副作用 | 任务锁 + 断点恢复前检查提交/回写状态 |

## 八、结论

**可直接实施**，无阻塞基础设施缺失。Jenkins 真实执行需 `ai-test-*` Job（现有白名单为 `ct-jeebootx-sanitation`/`jeebootx-ui`，属生产 Job → P11 的 Jenkins Adapter 只做 Mock + 接口，真实执行留待 `ai-test-*` 就绪）。
