# human-decision — Agent Human-in-the-Loop 人工决策闭环

Agent 遇到重大决策（P0/P1）时自动暂停、通知钉钉、等待用户回复、验证身份、
恢复**原 Claude Code Session** 并按用户决策继续执行的完整闭环。
属于 Agent Execution Manager（P11）的通用能力，与禅道/钉钉业务解耦。

## 架构

```text
Claude Code Agent
       |  request_human_decision (MCP, 有界阻塞等待)
       v
Decision Manager ── Decision Detector (P0/P1/P2)
       |    |
       |    +── Decision Store（SQLite，复用 agent-manager/logs/agent_manager.db）
       |
       +── DingTalk Notifier（cc-connect send，复用现有通道）
       |         |
       |         v
       |      钉钉用户 ──回复──> cc-connect
       |                          |  hook(CC_HOOK_*) 或 会话文件轮询（零配置兜底）
       |                          v
       +── Reply Handler（解析/身份校验/幂等）──> Decision Store
       |
       +── Session Resumer
               1) live_continue      原进程存活：工具取回 / Management API /send 注入
               2) cc_connect_resume  原生 agent_session_id --resume 续接
               3) checkpoint_rebuild execution/{project}/{task}/human-decision/ 检查点包
```

## 模块

| 文件 | 职责 |
|---|---|
| `models.py` | 决策数据结构与状态机（幂等转移守卫） |
| `decision_store.py` | SQLite 持久化（human_decisions / decision_replies / decision_events） |
| `decision_detector.py` | P0/P1/P2 分级 |
| `decision_manager.py` | 生命周期统一编排（唯一入口） |
| `notifier.py` | 钉钉决策通知（cc-connect send）+ 通知文案 |
| `reply_parser.py` / `reply_handler.py` | 回复解析、身份白名单、幂等、串任务防护 |
| `session_resumer.py` | 三级恢复策略 + 恢复包 |
| `timeout_handler.py` | 超时提醒（**绝不自动批准**） |
| `recovery_handler.py` | 进程重启对账 |
| `mcp_server.py` | MCP 工具：`request_human_decision` / `get_human_decision` / `list_human_decisions` |
| `cli.py` | daemon / hook / serve / reply / create / status / recover / complete |

## 状态机

```text
CREATED -> NOTIFY_FAILED -> NOTIFIED -> WAITING_REPLY -> DECISION_RECEIVED
        -> RESUMING -> RESUMED -> COMPLETED
异常：DECISION_TIMEOUT（迟到回复仍生效） / RESUME_FAILED / REJECTED（用户 STOP）
```

## 回复格式（钉钉内）

```text
A                 选择方案 A
A 说明文字         选择 + 意见
C 自定义意见       未定义选项 = 自定义意见
STOP / 停止 / 暂停 暂停任务
DEC-3413-001 A    显式绑定决策编号（多决策并行时必须）
```

## 使用

### MCP 注册（Agent 侧）

项目级：仓库根 `.mcp.json` 已注册（相对路径，随仓库生效）。
用户级（cc-connect 起的 Agent 用这个）：

```bash
claude mcp add human-decision --scope user -- python D:/WorkSpace/task-workflow/agent-manager/human_decision/mcp_server.py
```

### 常驻服务（回复收集 + 超时提醒 + 重启对账）

```bash
python agent-manager/human_decision/cli.py daemon
```

### cc-connect 回复接入（可选，权威身份）

`~/.cc-connect/config.toml` 追加后 `POST /api/v1/reload`（无需重启）：

```toml
[[hooks]]
event = "message.received"
type = "command"
command = "python D:/WorkSpace/task-workflow/agent-manager/human_decision/cli.py hook"
async = true
timeout = 10
```

未配置 hook 时自动使用会话文件轮询（单聊可验证身份；群聊默认拒绝）。

### 手动操作

```bash
python cli.py status [--decision-id DEC-...]
python cli.py reply --text "A" [--user-id ...] [--session-key ...]
python cli.py recover
python cli.py complete --decision-id DEC-...
```

## 配置

`config/adapters/hitl.yaml`（见 `hitl.example.yaml`）。敏感项：
`CC_MGMT_TOKEN`（.env）或自动读取 `~/.cc-connect/config.toml [management] token`。
授权决策人白名单：`human_decision.decoders`（user_id）。

## 测试

```bash
cd agent-manager && python -m pytest human_decision/tests -q
```

## 安全约束

- 未获批准绝不放行：等待超时 → 安全挂起，绝不自动批准。
- 一决策仅一次有效回复（原子状态守卫 + msg_id 去重）。
- 决策绑定 cc-connect 会话键，跨会话/跨任务回复不生效；多决策并行要求显式 DEC-ID。
- 仅授权决策人（白名单）的回复生效；群聊无身份验证时默认拒绝。
- 凭据不落库、不进日志（management token 仅存内存）。
