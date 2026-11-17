# HITL + Agent Execution Manager 验收报告

> 2026-11-17 · 测试基线：HITL 48 + agent-manager 20 = **68 PASS / 0 FAIL**

## 一、架构与运行环境

| 项 | 状态 |
|---|---|
| HITL 模块 | 13 模块 2671 行（`agent-manager/human_decision/`） |
| MCP | `human-decision`（3 工具：request/get/list_human_decision） |
| MCP 注册 | ✅ **已修**：用户级 `~/.claude.json` + 绝对路径（D1） |
| 钉钉通道 | `dingtalk_direct`（官方 `oToMessages/batchSend`）+ `cc_connect` 兜底 |
| 凭据解析 | 三级：env → `~/.dingtalk-skills/config` → cc-connect config.toml（不落盘） |
| SQLite | 复用现有，3 表 + **新增 msg_id UNIQUE**（D2） |
| cc-connect | 进程运行中（PID 31308）；**注**：未注册为 Windows 服务（`sc query` 1060） |

## 二、HITL 验收结果

| # | 项 | 状态 | 证据 |
|---|---|---|---|
| 1 | 唯一生命周期入口 | ✅ PASS | `DecisionManager` 6 方法全覆盖 |
| 2 | 决策状态机完整 | ✅ PASS | 11 状态 + 合法流转映射 |
| 3 | SQLite 持久化 | ✅ PASS | 3 表 |
| 4 | 重复通知/回复幂等 | ✅ PASS | **D2 修复后**：3 次同 msg_id 插入 → 1 条 |
| 5 | 未授权用户拒绝 | ✅ PASS | **D3 修复后**：fail-closed，陌生 ID/空 ID 全拒 |
| 6 | 旧消息误操作新任务 | ✅ PASS | 时间戳校验（早于决策 60s 拒绝） |
| 7 | 超时只提醒不自动批准 | ✅ PASS | `auto_approved: False` + 铁律注释 |
| 8 | Agent 阻塞超时处理 | ✅ PASS | `tool_wait_seconds=300` 有界等待 |
| 9 | Session 恢复三级降级 | ✅ PASS | live_continue → cc_connect_resume → checkpoint_rebuild |
| 10 | 重启对账未完成决策 | ✅ PASS | `recovery_handler.recover()` 不重复创建、补发通知 |

## 三、修复的 3 个真实缺陷

### D1 · MCP 路径相对化（阻断 cc-connect 场景）
`.mcp.json` 相对路径在 CWD 非项目根时解析失败 → cc-connect 启动的 Agent 加载不到 MCP。
**修复**：注册到用户级 `~/.claude.json`（`python -I <绝对路径>`），已备份原配置。
**验证**：CWD=`/d/WorkSpace`、`~` 均可导入，`DecisionManager` 可用。

### D2 · decision_replies 缺 msg_id UNIQUE（并发幂等漏洞）
**修复**：加 `UNIQUE(decision_id, msg_id)` 索引 + `INSERT OR IGNORE`。
**验证**：同 msg_id 插 3 次 → 1 条记录。

### D3 · `any_private_chat_user=true` 默认放行所有私聊（越权风险）
实测：`user=99999`（陌生 ID）和空 userId 都能通过身份校验 → 违反 A04。
**修复**：默认改 fail-closed + 加 `hitl.local.yaml` 本地配置层 + `HITL_DECIDER_IDS` 环境变量 + `config_error()` 明确提示。
**验证**：默认下全拒；配置决策人后白名单放行、陌生 ID 拒绝；env 覆盖生效。

## 四、团队本地配置（T04/T05）

| 文件 | 用途 | Git |
|---|---|---|
| `config/adapters/hitl.yaml` | 通用配置 | 提交 |
| `config/adapters/hitl.local.yaml` | 个人 userId | **gitignored** |
| `config/adapters/hitl.local.example.yaml` | 模板 | 提交 |
| 环境变量 `HITL_DECIDER_IDS` | 覆盖 | 不提交 |

**分层加载**：DEFAULTS → hitl.yaml → hitl.local.yaml → 环境变量
**新成员接入**：复制 `hitl.local.example.yaml` → `hitl.local.yaml`，填自己的 userId，无需改源代码。
**gitignore 已验证**：`git check-ignore` 确认 `hitl.local.yaml` 不入库。

## 五、Agent Execution Manager 加固

| 项 | 状态 | 说明 |
|---|---|---|
| T06 任务状态 | ✅ PASS | 新增 `WAITING_HUMAN`，`task_state_hook` 桥接决策↔任务 |
| T07 失败检测 | ✅ PASS | `FailureDetector` 8 种类型（正常/非零/超时/进程消失/MCP/通知/HITL/未知） |
| T07 异常分类 | ✅ PASS | 扩展 FAULT_KEYWORDS：MCP/通知=TRANSIENT，HITL/进程=HUMAN/PERMANENT |
| T08 有限重试 | ✅ 已有 | `RetryPolicy` max_attempts=2 + 指数退避 + 副作用检查 |
| T09 进程恢复 | ✅ 已有 | `recovery_handler.recover()` 对账、不重复创建 |
| T10 并发幂等 | ✅ PASS | **D2 msg_id UNIQUE** + 任务锁复用 |
| T11 执行日志 | ✅ 已有 | `audit.jsonl` + `decision_events` 表 |
| T12 状态查询 | ✅ PASS | **补 `waiting`/`failures` 命令**（原只有 run/status/history/list） |

## 六、测试报告

| 套件 | 数量 | 结果 |
|---|---|---|
| HITL (`human_decision/tests/`) | 48 | ✅ PASS |
| agent-manager (`tests/`) | 20 | ✅ PASS |
| **合计** | **68** | **PASS / 0 FAIL** |

**异常路径覆盖**：D2 并发幂等、D3 越权拒绝、HITL 超时不批准、失败分类 8 种、任务状态桥接。

## 七、遗留问题

### 必须立即解决
- **无**

### 后续迭代
- `cc_connect_resume` 真实隔离测试（P1，需独立测试任务避免干扰）
- 并发压力测试
- 执行统计完善（Token/工具调用数）

### 外部环境限制
- cc-connect 未注册为 Windows 服务（进程直跑），服务化部署待办
- 真实钉钉端到端闭环需真实账号验证（本次凭据解析/身份校验/通知接口均已验证）

## 八、Git 交付

- 分支 `main`
- **修改**：`hitl_config.py`（fail-closed + 分层加载）、`hitl.yaml`、`decision_store.py`（D2）、`models.py`（WAITING_HUMAN）、`decision_manager.py`（task_state_hook）、`retry.py`（T07 分类）、`cli.py`（T12 查询）、2 个测试、`.gitignore`
- **新增**：`failure_detector.py`、`config/adapters/hitl.local.example.yaml`、`reports/HITL_*.md`
- **外部**：`~/.claude.json` 加 MCP（已备份）
- 凭据扫描：CLEAN（无 userId/secret 入库）

## 九、最终结论

| 问题 | 回答 |
|---|---|
| 1. HITL 可稳定投入日常使用？ | **PARTIAL** — 核心链路（决策/通知/恢复/幂等）PASS，真实钉钉闭环待账号验证 |
| 2. 团队成员可独立配置使用？ | **PASS** — `hitl.local.yaml` + env 覆盖，无需改源代码，gitignore 已验证 |
| 3. Agent 失败后能正确发现通知？ | **PASS** — `FailureDetector` 8 类 + 通知链路 |
| 4. 可有限自动重试？ | **PASS** — TRANSIENT 重试、HITL/永久不重试（已验证） |
| 5. 重启后正确恢复任务？ | **PASS** — `recover()` 对账、不重复创建（已有实现 + 测试） |
| 6. 影响正式使用的风险？ | cc-connect 未服务化；真实钉钉端到端待验证；`cc_connect_resume` 隔离测试待补 |

## 验收项汇总（A01-A10）

| 编号 | 项 | 结果 |
|---|---|---|
| A01 | HITL 运行环境 | **PARTIAL**（MCP/通知链路 PASS，cc-connect 服务化待办） |
| A02 | 私聊决策闭环 | **PARTIAL**（代码+单测 PASS，真实钉钉待账号验证） |
| A03 | 团队本地配置 | **PASS** |
| A04 | 身份安全 | **PASS**（D3 fail-closed） |
| A05 | Agent 失败检测 | **PASS**（T07 8 类） |
| A06 | 有限自动重试 | **PASS**（T08） |
| A07 | 状态持久化 | **PASS**（SQLite + D2） |
| A08 | 重启恢复 | **PASS**（T09） |
| A09 | 并发隔离 | **PASS**（D2 msg_id UNIQUE + 任务锁） |
| A10 | 测试与文档 | **PASS**（68 测试 + 本报告） |
