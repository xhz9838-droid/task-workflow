# HITL 运行环境盘点（T01）

> 2026-11-17 · 只读盘点 · 测试基线 48 passed

## 一、模块结构（13 模块，2671 行 + 5 测试文件）

| 模块 | 行数 | 职责 |
|---|---|---|
| `decision_manager.py` | 235 | **生命周期唯一入口**（create/wait/apply_reply/recover/check_timeouts/complete） |
| `decision_store.py` | 368 | SQLite 持久化（3 表） |
| `reply_handler.py` | 413 | 回复处理、身份校验、幂等 |
| `notifier.py` | 308 | 钉钉通知（dingtalk_direct 优先 + cc_connect 兜底） |
| `session_resumer.py` | 261 | 三级恢复降级 |
| `models.py` | 255 | 决策状态机 |
| `cli.py` | 213 | 命令行入口 |
| `hitl_config.py` | 175 | 配置加载 |
| `decision_detector.py` | 109 | 决策意图识别 |
| `mcp_server.py` | 115 | MCP 工具（Agent 调用） |
| `reply_parser.py` | 89 | 回复解析 |
| `timeout_handler.py` | 78 | 超时提醒/标记 |
| `recovery_handler.py` | 52 | 重启对账 |

## 二、验收要点逐项核对

| # | 要点 | 状态 | 证据 |
|---|---|---|---|
| 1 | 唯一生命周期管理入口 | ✅ 已实现 | `DecisionManager` 单类，6 个公开方法覆盖全生命周期 |
| 2 | 决策状态机完整 | ✅ 已实现 | 11 状态 + `_allowed_transitions` 合法流转映射（models.py:52-73） |
| 3 | 决策记录持久化 SQLite | ✅ 已实现 | `human_decisions`/`decision_replies`/`decision_events` 三表 |
| 4 | 重复通知/回复幂等保护 | ⚠️ **部分** | 应用层幂等（msg_id 已处理→duplicate），但**表无 UNIQUE 约束** |
| 5 | 未授权用户拒绝 | ⚠️ **部分** | `_check_identity` 有白名单，但默认 `any_private_chat_user=true` 放行所有私聊 |
| 6 | 旧消息误操作新任务 | ✅ 已实现 | 时间戳校验（reply_handler.py:86-87）：早于决策创建 60s 的消息拒绝 |
| 7 | 超时只提醒不自动批准 | ✅ 已实现 | timeout_handler 铁律注释 + `auto_approved: False` 记录 |
| 8 | Agent 阻塞超时/异常处理 | ✅ 已实现 | `tool_wait_seconds=300` 有界等待 |
| 9 | Session 恢复三级降级 | ✅ 已实现 | `live_continue` → `cc_connect_resume` → `checkpoint_rebuild` |
| 10 | 重启对账未完成决策 | ✅ 已实现 | `recovery_handler.recover()`：恢复 WAITING_*、补发通知、不重复创建 |

## 三、发现的缺陷（3 项）

### D1 · MCP 路径相对化（阻断 cc-connect 场景）
`.mcp.json` 用相对路径 `agent-manager/human_decision/mcp_server.py`。
→ **CWD 不同时 MCP 加载失败**。手动终端 vs cc-connect 启动的工作目录不一致时，MCP 不可用。
**影响**：T02 验收 A01。**修复**：改为绝对路径或基于 `__file__` 解析。

### D2 · decision_replies 缺 msg_id UNIQUE 约束
幂等靠应用层查重，**并发下可能重复入库**。
**影响**：A09 并发隔离。**修复**：加 `UNIQUE(decision_id, msg_id)` 或 `msg_id` 唯一索引。

### D3 · 默认 `any_private_chat_user=true` 放行所有私聊
`deciders: []` + `any_private_chat_user: true` 时，**任何私聊用户都被视为授权决策人**（best-effort）。
**影响**：A04 身份安全，团队使用时越权风险。**修复**：默认收紧，团队成员必须显式配置 userId。

## 四、配置现状

- `config/adapters/hitl.yaml`：非敏感配置齐全（超时/通知/恢复策略）
- `.mcp.json`：`human-decision` MCP 注册（**路径缺陷见 D1**）
- 敏感项（management token）走 `.env CC_MGMT_TOKEN` 或自动读 cc-connect config.toml —— **未落盘** ✅
- **未发现 Python 代码硬编码 userId** ✅（配置文件中有注释示例，非硬编码）

## 五、Git 现状

- 分支 `main`，最新 3 提交为 HITL 相关（另一会话已完成部分实现）
- 未提交：`execution/3413/`、`execution/hitl-e2e/`、`reports/hitl-e2e*` 等运行产物
- **注意**：HITL 模块已存在且有测试，**不重复开发**，只做验收 + 修复

## 六、运行环境

- cc-connect：已注册 Windows 服务（按前提，不重复实施服务注册）
- 钉钉：仅私聊（本阶段唯一场景）
- SQLite：复用现有，不引入 Redis/MQ
