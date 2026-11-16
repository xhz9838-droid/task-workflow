# Agent Execution Manager（P11）

智能任务路由 + Agent 生命周期管理 + 结果验证的自动化开发执行系统。

在 P01-P10 通用化工作流框架上**增量升级**，不取代 Claude Code 的 Main Agent / Subagents，
而是管理它们的**外部执行生命周期**。

## 核心能力

| 模块 | 职责 |
|---|---|
| `task_router.py` | **S/M/L 智能分级** + 派发策略 + 用户指令优先 |
| `models.py` | 数据模型、Agent 状态机、验证五态 |
| `exceptions.py` | 异常体系（携带 FaultClass 决定重试策略） |
| `state_manager.py` | SQLite 状态持久化 + 任务锁 + 断点恢复 |
| `runner.py` | Claude Code 子进程启动/超时/取消/进程树终止 |
| `monitor.py` | 进程/心跳/输出/阶段**四概念分离**监控 |
| `retry.py` | 有限重试 + 故障分类（瞬时/永久/人工） |
| `verifier.py` | 结果验证质量门禁 + BLOCKED 聚合 |
| `zentao_reporter.py` | 禅道回写（**复用现有适配器**） |
| `notifier.py` | 钉钉事件通知（**复用 CC Connect**） |
| `jenkins_adapter.py` | Jenkins CI 接管（`ai-test-*` 白名单） |

## 任务分级（Task Router）

```
S 简单  → Main Agent 直通，0 子 Agent
   单文件/少量文件、UI/CSS/文案、简单 Bug、配置改动

M 中等  → 按需选择性子 Agent
   多文件、中等业务逻辑、单仓库多模块、涉及 API/组件契约

L 大型  → 完整多 Agent 工作流
   跨仓库、复杂业务、DDL 变更、多模块协作、高风险安全逻辑
```

**不只看文件数**：综合业务复杂度、跨仓库、DB 变更、API 契约、安全风险、回滚难度、测试环境要求。
高风险情况即使单文件也**不归 S**。

**用户指令优先**：明确说"不用子 Agent / 跳过 Build / 只做静态检查"时，覆盖默认工作流。

## 快速使用

```python
from agent_manager.task_router import TaskRouter, TaskSignal

router = TaskRouter()
decision = router.classify(
    task_id="3413",
    project_key="jeebootx",
    signal=TaskSignal(
        file_count=1,
        description="修改按钮文案 css 样式",
        file_paths=["src/views/Button.vue"],
    ),
)
print(decision.task_level)        # TaskLevel.S
print(decision.selected_agents)   # []  ← 简单任务不启动子 Agent
```

## 运行集成测试

```bash
python -I agent-manager/tests/test_integration.py
```

结果：**56 PASS / 0 FAIL**（纯 Mock，不依赖生产环境）。

## CLI 目标接口

```bash
python agent-manager/runner.py --project jeebootx --task-id 3413
python agent-manager/runner.py --resume --project jeebootx --task-id 3413
python agent-manager/monitor.py --project jeebootx --task-id 3413
python agent-manager/monitor.py --list
python agent-manager/verifier.py --report --project jeebootx --task-id 3413
```

> 上述为设计接口，`runner.py`/`monitor.py` 目前提供核心类，CLI 参数解析待封装。

## 关键设计约束

### 验证五态（铁律）

```
PASS     实际执行且通过
FAIL     实际执行但失败
BLOCKED  环境/权限原因无法执行
SKIPPED  按策略或用户要求跳过
NOT_RUN  尚未执行
```

**BLOCKED / SKIPPED / NOT_RUN 绝不标记为 PASS。**

### 故障分类与重试

| 分类 | 例子 | 策略 |
|---|---|---|
| TRANSIENT | 网络抖动、超时、502/503/504 | 自动重试（默认 2 次，指数退避） |
| PERMANENT | 代码错误、测试失败、ESLint、缺依赖 | **交回 Main Agent 分析**，不盲目重启 |
| HUMAN | 用户取消、业务决策、状态冲突 | 停止，请求人工 |

重试前检查副作用（已提交/已回写禅道/有副作用 → 不盲目重试）。

### 监控四概念（不混为一谈）

```
Process Alive    操作系统进程存活
Heartbeat        管理器确认 Agent 正常执行（无可靠源时标 unavailable，不伪造）
Output Activity  最近是否有输出
Workflow Progress 是否推进到下一阶段
```

**Claude Code 思考时可能长时间无输出，输出静默只告警、不杀进程。**

### 安全约束

- 不自动部署、不重启业务服务
- 不自动执行禅道 `task_finish` / `task_close`
- 不伪造工时、完成日期、测试结果
- Jenkins 只允许 `ai-test-*`，禁止生产构建/部署
- 凭据不写入配置/日志/命令行

## 状态存储

SQLite（`agent-manager/logs/agent_manager.db`，gitignored）：

| 表 | 用途 |
|---|---|
| `execution_runs` | 任务级执行 |
| `agent_runs` | 子 Agent 运行 |
| `execution_events` | 事件流（审计/恢复） |
| `verification_results` | 验证结果 |
| `task_locks` | 任务级锁（防重复启动） |
| `pending_writes` | 待回写禅道事件（失败不丢） |

## 配置

`agent-manager/config.yaml`（可被项目级配置覆盖）：

```yaml
execution:
  max_concurrent_tasks: 1
  task_lock_enabled: true
  resume_enabled: true

routing:
  simple: { subagents: false, workflow: direct }
  medium: { workflow: selective }
  large:  { workflow: full }

retry:
  max_attempts: 2
  exponential_backoff: true

verification:
  run_build_by_default: false
  aggregate_blocked_checks: true

jenkins:
  enabled: false
  mock: true
  allowed_job_prefix: "ai-test-"

notification:
  enabled: true
  reuse_existing_channel: true
```

敏感凭据走 `.env`，**绝不**写入 YAML。

## 基础设施待办

| 项 | 状态 |
|---|---|
| `ai-test-*` Jenkins Job | ⬜ 待创建（现有 Job 均为生产部署 Job） |
| Jenkins 节点 Git 只读凭据 | ⬜ 待配置 |
| Jenkins Tool Check（Java/Maven/Node） | ⬜ 待验证 |
| CC Connect 钉钉通道 | ✅ 可用（复用现有） |
| ZenTao 适配器 | ✅ 可用（复用现有） |

当前 Jenkins Adapter 以 **Mock 模式**运行（不计为通过）。
真实执行待 `ai-test-*` Job 就绪后将 `config.yaml → jenkins.enabled=true, mock=false`。

## 依赖

Python 标准库（`sqlite3` / `subprocess` / `threading` / `json` / `datetime`）。
`psutil` 可选（有则用于 PID 检测，无则用 ctypes/kill 兜底）。
