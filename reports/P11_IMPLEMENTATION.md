# P11 实施报告：智能任务路由与 Agent Execution Manager

> 2026-11-16 · 增量升级，未破坏 P01-P10

## 一、实施结果

### 新增模块 `agent-manager/`（3221 行，13 文件）

| 文件 | 行数 | 职责 | 状态 |
|---|---|---|---|
| `task_router.py` | 264 | S/M/L 智能分级 + 派发策略 + 用户指令优先 | ✅ |
| `models.py` | 252 | 数据模型、Agent 状态机、验证五态 | ✅ |
| `exceptions.py` | 109 | 异常体系（携带 FaultClass） | ✅ |
| `state_manager.py` | 430 | SQLite 持久化 + 任务锁 + 断点恢复 | ✅ |
| `runner.py` | 249 | Claude Code 子进程生命周期 | ✅ |
| `monitor.py` | 245 | 四概念分离监控 | ✅ |
| `retry.py` | 259 | 有限重试 + 故障分类 | ✅ |
| `verifier.py` | 299 | 结果验证门禁 + BLOCKED 聚合 | ✅ |
| `zentao_reporter.py` | 213 | 禅道回写 | ✅ |
| `notifier.py` | 242 | 钉钉事件通知 | ✅ |
| `jenkins_adapter.py` | 265 | Jenkins CI 接管 | ✅ |
| `config.yaml` | — | 统一配置 | ✅ |
| `tests/test_integration.py` | 357 | 集成测试 | ✅ |

### P01-P10 能力复用（不重复开发）

| 资产 | 复用方式 |
|---|---|
| ZenTao Client + 认证 | `zentao_reporter.py` 调 `scripts/zt.py`，**未新建客户端** |
| Jenkins REST 客户端 | `jenkins_adapter.py` 调 `scripts/jenkins_run.py`，**未重写** |
| CC Connect 钉钉 | `notifier.py` 调 `scripts/notify.sh`，**未建新机器人** |
| 配置加载（6 层） | `config.yaml` 与现有 `scripts/_config.py` 体系兼容 |
| 任务状态隔离 | 沿用 `execution/{project_key}/{task_id}/` |
| Skill + 7 Subagents | 保留，Agent 派发名沿用 `dw-*` |
| Git Worktree | 未改动机制 |

### 未修改的（保护项）

- P01-P10 Git 历史（`63b12bc`…`8d11874`）未重写
- `execution/jeebootx/3413/*`（W1/QA1 运行产物）未改写
- `.worktrees/jeebootx-ui-zt3413`（W1 commit `1c302d6`）未动
- `scripts/jenkins_run.py_a`、`scripts/start-claude.sh`（用户文件）未动
- 业务仓库脏文件未动
- **未自动部署**
- 禅道 `task_finish` 经 Verifier 门禁后允许自动执行（须读回确认）；`task_close` 始终禁止自动

## 二、测试结果

### 集成测试：56 PASS / 0 FAIL

```bash
python -I agent-manager/tests/test_integration.py
```

| 场景 | 结果 |
|---|---|
| 1 简单任务 0 Subagent | ✅ PASS |
| 2 中等任务选择性 Agent | ✅ PASS |
| 3 复杂任务完整流程 | ✅ PASS |
| 高风险单文件不归 S | ✅ PASS |
| 4/17 用户指令优先（禁子 Agent / 跳过 Build / 仅静态） | ✅ PASS |
| 5/6/7 Agent 生命周期（进程存活 / 超时杀 / 输出静默不杀） | ✅ PASS |
| 8 瞬时错误自动重试 | ✅ PASS |
| 9 代码错误不盲目重试（交回 Main Agent） | ✅ PASS |
| 11 重复 task_id 不重复启动（任务锁） | ✅ PASS |
| 12 Verifier 拒绝错误成功状态 | ✅ PASS |
| 13 BLOCKED 正确聚合 | ✅ PASS |
| 15 钉钉重复事件去重 | ✅ PASS |
| 16 Jenkins Job 白名单（生产 Job 拒绝） | ✅ PASS |
| 验证五态铁律（仅 PASS 算通过） | ✅ PASS |
| 越权修改检测 | ✅ PASS |
| 状态持久化 + 断点恢复 | ✅ PASS |
| 通知失败不阻塞任务 | ✅ PASS |

### 测试覆盖（真实执行）

| 类别 | 状态 | 说明 |
|---|---|---|
| 单元/集成 | ✅ **PASS** | 56 项，纯 Mock |
| Windows 兼容性 | ✅ **PASS** | UTF-8 强制、ctypes PID、CREATE_NEW_PROCESS_GROUP |
| Agent 生命周期 | ✅ **PASS** | 启动/超时/取消/进程树终止 |
| 异常恢复 | ✅ **PASS** | SQLite 持久化 + 重启后读取 |
| 禅道适配器 | ✅ **PASS** | Mock（dry_run）；真实写入走既有状态流转规则 |
| 钉钉通知 | ✅ **PASS** | Mock（dry_run）+ 去重；真实发送走 CC Connect |
| Jenkins | ⏸ **MOCK** | 基础设施未就绪（无 `ai-test-*` Job） |

### 未测量项（诚实标注）

| 项 | 状态 | 原因 |
|---|---|---|
| Token 使用量 | NOT_RUN | 无法从子进程可靠获取 |
| 工具调用次数 | NOT_RUN | 需 Claude Code 会话元数据 |
| 真实禅道写入 | **已授权** | `task_finish` 经 Verifier 门禁后自动执行+读回确认；`task_close` 禁止自动 |
| 真实 Jenkins 构建 | BLOCKED | 无 `ai-test-*` Job |

## 三、Git 信息

- 分支：`main`
- 基于：`8d11874`（P01-P10 通用化）
- 新增：`agent-manager/`（13 文件）+ `reports/P11_*.md`
- 修改：`.gitignore`（排除运行数据）
- 工作区：`execution/jeebootx/3413/*` 保留未提交（3413 运行产物）

## 四、基础设施待办

### Jenkins（P1 接管前置）

| # | 待办 | 说明 |
|---|---|---|
| 1 | 创建 `ai-test-*` 测试 Job | 现有 Job 均为生产部署 Job，禁止用作实验 |
| 2 | Jenkins 节点 Git 只读凭据 | 用于 checkout 业务仓库 |
| 3 | 节点 Tool Check | 验证 Java/Maven/Node 可用 |
| 4 | 拉通一次 `ai-test-runner` 验证 | 就绪后 `config.yaml → jenkins.enabled=true, mock=false` |

### CC Connect 钉钉

✅ 已就绪（复用现有通道）。事件通知走 `scripts/notify.sh → cc-connect send`。

**限制**：CC Connect 无 Python 直连接口，通知由管理器经 CLI 调用；
若需进程内事件交接，可用 `pending_writes` 表 + 定时 flush。

### 其他

| 项 | 说明 |
|---|---|
| Runner CLI 封装 | `runner.py` 提供 `AgentRunner` 类；`argparse` CLI 待封装 |
| Monitor CLI 封装 | `monitor.py` 提供 `Monitor` 类；`--list`/`--status` 待封装 |
| Skill 增量规范 | Task Classification / Dispatch Policy 等已实现在 `task_router.py`；Skill 文档同步待补 |

## 五、效率对比（S/M/L）

### 实测（同任务 3413：单文件 105 行纯前端）

| 指标 | P11 前（实际） | P11 后（路由预期） |
|---|---|---|
| 任务分级 | 无（走完整流程） | **S** |
| Subagent 数 | 3 Explore + W1 + QA + IR = 6 | **0** |
| 工具调用 | QA1 单个即 29 次 | **~5 次**（Main 直接改） |
| 总耗时 | QA1 单步 21 分钟 | **<2 分钟** |
| 无效测试 | `npm run build` 6m49s（已说跳过） | **不启动** |
| BLOCKED 记录 | 12 条逐条长文 | **聚合 1 条** |

**实测依据**（非估算）：
- QA1 报告 `execution/jeebootx/3413/agent-reports/qa-engineer-1.json`
- build 耗时 6m49s、29 次工具调用、12 条 BLOCKED

### 路由验证（集成测试实测）

```
S: file_count=1, "修改按钮文案 css 样式"
   → level=S, agents=[], workflow=direct, tests=[static,lint,build]
   理由: 小范围修改（1 文件）| 命中简单变更特征 | 无数据库/API/安全/跨仓库风险

M: file_count=6, "修改薪酬模块业务逻辑"
   → level=M, agents=[dw-qa-engineer, dw-web-frontend], workflow=selective

L: file_count=12, "跨仓库新增薪酬审批 DDL 接口契约"
   → level=L, agents=[dw-architect, dw-database, dw-integration-reviewer,
                      dw-java-backend, dw-qa-engineer], workflow=full
```

## 六、当前可运行能力

### 可独立运行（真实）

| 模块 | 能力 |
|---|---|
| `task_router` | S/M/L 分级、派发、用户指令优先 |
| `state_manager` | SQLite 持久化、任务锁、断点恢复 |
| `retry` | 故障分类、指数退避、副作用保护 |
| `verifier` | Git 检查、五态判定、BLOCKED 聚合、越权检测 |
| `monitor` | 四概念监控、超时判定 |

### Mock 验证（真实调用待环境）

| 模块 | 状态 |
|---|---|
| `zentao_reporter` | dry_run 通过；`task_finish` 门禁后自动+读回确认，`task_close` 禁止 |
| `notifier` | dry_run + 去重通过；真实发送走 CC Connect |
| `jenkins_adapter` | Mock + 白名单通过；真实执行待 `ai-test-*` |
| `runner` | 类就绪；真实拉起 Claude Code 待 CLI 封装 |

### 下一步启动

```bash
# 1. 路由验证
python -I agent-manager/tests/test_integration.py

# 2. 待 Jenkins ai-test-* 就绪后
#    改 agent-manager/config.yaml: jenkins.enabled=true, mock=false

# 3. Runner CLI 封装后
python agent-manager/runner.py --project jeebootx --task-id 3413
```

## 七、与 P01-P10 的关系

- **不取代**：Claude Code Main Agent / Subagents 仍是执行主体
- **管理**：Agent Manager 管理它们的**外部执行生命周期**（启动/监控/超时/取消/恢复）
- **Skill 兼容**：`/zentao-dev-workflow {project_key} {task_id}` 手动调用方式不变
- **简单任务**：Router 判 S 级后 Main Agent 直通，**不启动子 Agent**（P11 核心目标）
