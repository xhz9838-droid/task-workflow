# HITL 人工决策闭环 — 实施报告

> 2026-11-16 · agent-manager/human_decision · 提交 757ae00
> 状态：核心实现与测试完成，真实钉钉端到端进行中（见 §4）

## 一、实施结果

### 新增模块（`agent-manager/human_decision/`，Python 3.13 stdlib + PyYAML + MCP SDK）

| 模块 | 职责 |
|---|---|
| `models.py` | 决策数据结构、状态机（原子转移守卫） |
| `decision_store.py` | SQLite 持久化（复用 `agent-manager/logs/agent_manager.db`，新增 human_decisions / decision_replies / decision_events 表） |
| `decision_detector.py` | P0/P1/P2 决策分级（关键词规则 + 显式指定优先） |
| `decision_manager.py` | 生命周期统一编排（唯一入口，含审计接入 scripts/audit.py） |
| `notifier.py` | 钉钉决策通知（复用 cc-connect send，重试 + 失败不放行） |
| `reply_parser.py` / `reply_handler.py` | 回复解析（A/B/C+意见/STOP/DEC-ID）、身份白名单、幂等、串任务防护、双回复源（hook + 会话文件轮询） |
| `session_resumer.py` | 三级恢复 + 恢复包（resume-packet.md / decision.json） |
| `timeout_handler.py` | 超时提醒与超时标记（**绝不自动批准**） |
| `recovery_handler.py` | 进程重启对账（决策不丢、不重复创建、补发通知） |
| `mcp_server.py` | MCP 工具：`request_human_decision` / `get_human_decision` / `list_human_decisions` |
| `cli.py` | daemon / hook / serve / reply / create / status / recover / complete / poll |
| `tests/`（5 个文件） | 46 项 pytest：单元 + 集成 + 异常 |

### 修改文件

| 文件 | 变更 |
|---|---|
| `config/adapters/hitl.yaml` + `hitl.example.yaml` | 新增 HITL 配置（白名单/超时/通道/恢复策略） |
| `.mcp.json` | 新增 MCP Server 注册（项目级） |
| `.env.example` | 新增 `CC_MGMT_TOKEN`（可选） |
| `.claude/skills/zentao-dev-workflow/references/human-decision-policy.md` | 新增 Human Decision Policy 规范 |
| `.claude/skills/zentao-dev-workflow/SKILL.md` | references 表增加一行（已随并行提交入库） |
| `.claude/skills/zentao-dev-workflow/templates/agent-report.json` | 报告模板增加 `human_decision` 块 |

### 与 Agent Execution Manager 集成

- 持久化复用同一 SQLite（`agent-manager/logs/agent_manager.db`），表结构只增不改，不破坏 Runner/Monitor/State Manager。
- 审计复用 `scripts/audit.py`（`human_decision.create` / `human_decision.reply`）。
- 通知复用 `cc-connect send`（与 `scripts/notify.sh` 同通道），不新建通信系统。
- 通用能力与禅道业务解耦：模块内无禅道/钉钉硬编码；绑定经 cc-connect 环境变量（CC_PROJECT/CC_SESSION_KEY）与配置。

## 二、架构说明

```text
Claude Code Agent
       |  request_human_decision (MCP stdio, 有界阻塞等待)
       v
Human Decision Manager ── Decision Detector (P0/P1/P2)
       |    |
       |    +── Decision Store（SQLite/WAL，共享 agent_manager.db）
       |
       +── DingTalk Notifier（cc-connect send）
       |         |
       |         v
       |      钉钉用户 ──回复──> cc-connect（v1.5.0）
       |                          |  message.received hook（CC_HOOK_*，权威身份）
       |                          |  或 会话文件轮询（零配置兜底）
       |                          v
       +── Reply Handler（解析/身份/幂等）──> Decision Store
       |
       +── Session Resumer
               1) live_continue      原进程存活：阻塞工具自取回 / Management API /send 注入
               2) cc_connect_resume  原生 agent_session_id --resume 续接
               3) checkpoint_rebuild execution/{project}/{task}/human-decision/ 检查点包
       v
Original Claude Code Session → Continue Execution
```

**执行阻塞**：MCP 工具轮询共享决策库；超时（默认 300s）返回 `suspended`，Agent 必须停止依赖该决策的操作（安全挂起），未获批准绝不放行。

**上下文连续**：恢复优先级一 = 工具从未离开原 Session（同回合继续）；优先级二 = cc-connect 原生 `--resume`（agent_session_id 持久化，二进制/文档/实测三重确认）；优先级三 = 恢复包（任务上下文 + 决策 + 执行状态）。

## 三、关键技术决策（证据基础）

1. **cc-connect 实测能力**（v1.5.0，二进制字符串 + 实测 + 官方文档交叉验证）：
   - `send --stdin -p -s` 发钉钉；Management API `POST /api/v1/projects/{name}/send`（要求 live）；
   - agent 环境注入 `CC_PROJECT`/`CC_SESSION_KEY`；`agent-sid` 输出 `--resume` 用 session id；
   - 二进制含 `CC_HOOK_USER_ID/USER_NAME/SESSION_KEY/CONTENT/...`（message.received hook 事件）；
   - "queued user messages" 证实 Agent 忙时用户消息排队不丢。
2. **不用 MCP 工具无限阻塞**：cc-connect 有 `turn_timeout_mins`/`idle_timeout_mins` 会释放卡死会话 → 有界等待 + 安全挂起 + 恢复，符合"不能假设 MCP 可无限期阻塞"的约束。
3. **消息关联**：决策绑定 `CC_SESSION_KEY`（钉钉会话键含用户 ID），多决策并行时要求显式 DEC-ID 回复，禁止"最近一条消息"式匹配。
4. **Windows 二进制解析**：Python subprocess 无法解析 npm 包装脚本，`resolve_cc_connect_bin()` 显式解析 `.cmd`（E2E 中实测踩坑并修复）。

## 四、测试结果

### 单元 + 集成测试：**46 / 46 通过**（`python -m pytest human_decision/tests -q`）

| 测试域 | 覆盖 | 结果 |
|---|---|---|
| 模型/检测/解析 | 状态机守卫、P0/P1/P2、全部回复格式 | ✅ 通过 |
| 存储 | CRUD、原子转移、msg_id 去重、跨实例持久化 | ✅ 通过 |
| 回复处理 | 身份白名单、重复回复幂等、无效选项、STOP、跨会话/跨任务防串、旧消息过滤、会话文件轮询 | ✅ 通过 |
| Manager 集成 | 创建→通知→回复→恢复全流程、通知失败不放行、超时不自动批准、迟到回复、重启对账、多决策并行、闭环完成 | ✅ 通过 |
| Resumer | 三级恢复选择、恢复包生成、幂等 | ✅ 通过 |

### 异常测试（自动化，全部覆盖）：✅ 通过

- [x] 钉钉通知失败（重试后 NOTIFY_FAILED，决策继续等待，不放行）
- [x] 用户长时间不回复（提醒 + DECISION_TIMEOUT，绝不自动批准）
- [x] 用户重复回复（幂等：仅第一次生效）
- [x] 用户发送无效选项（INVALID_REPLY，仍等待）
- [x] 未授权用户回复（拒绝 + 仍等待）
- [x] Runner/进程重启（决策恢复、不重复创建、补发通知、session 绑定不丢）
- [x] 多任务同时等待（DEC-ID 精确关联，裸回复在歧义时不生效）
- [x] 决策完成后收到旧消息（状态守卫拒绝 / 旧消息时间过滤）

### 真实端到端测试（真实钉钉）：两轮

**第一轮（19:12–19:26，真实闭环 + 实测发现通道缺陷）**

| 项 | 状态 | 证据 |
|---|---|---|
| Agent 主动发起决策（真实 MCP 会话） | ✅ 已验证 | 决策 DEC-HITL-E2E-19130101 创建于 19:13:01（P1/方案/推荐齐全） |
| Agent 阻塞不越权 | ✅ 已验证 | tool_waiting 19:13:11 起阻塞 600s；19:23:12 超时 → **安全挂起**（outcome 文件仅写"任务已挂起"，未继续任何操作） |
| 用户钉钉回复 → 捕获/身份/入库 | ✅ 已验证 | 19:26:36 会话文件监听捕获用户（徐弘祖 / userId 17248148409976157）回复，决策 DECISION_RECEIVED；后续重复消息（"1"、"你好"）被幂等守卫拒绝（reply_rejected×2） |
| 决策注入/恢复记账 | ✅ 已验证 | RESUMING→RESUMED，resume_method 记录（含注入通道细节） |
| 钉钉收到决策通知（cc-connect send） | ❌ **实测失败** | `cc-connect send` 虚报 "Message sent successfully" 但消息不到达（5 种寻址全试）；同一凭据直调钉钉官方 API `oToMessages/batchSend` → 200 送达 ✅ |
| 通知通道修复 | ✅ 已完成 | 新增 `dingtalk_direct` 传输（官方机器人 API 直发优先，cc-connect 兜底），20:29 决策原文已补发 |

**第二轮（2026-11-16 夜）**：cc-connect 钉钉入站流静默失效（Windows 控制台「快速编辑模式」点击冻结进程所致，用户实证：点鼠标卡住、右键恢复），回复未达；Agent 等待 900s 后按设计**安全挂起**（未越权、未自动批准）。教训已入运维文档。

**第三轮（2026-11-17 09:29–09:30，完整闭环，56 秒）**

| 项 | 状态 | 证据 |
|---|---|---|
| 修复后钉钉收到决策请求 | ✅ 已验证 | DEC-HITL-E2E-3-09292801，09:29:28 直发无错误，用户确认收到 |
| 用户有意图回复 A → 工具同回合返回 | ✅ 已验证 | 09:30:24 用户（徐弘祖）回复 "A"，56 秒内：采集→身份校验→解析(option=A)→入库→RESUMED |
| 原 Session 恢复（live_continue） | ✅ **真实验证** | `resumed{method: live_continue, detail: "blocked tool polling decision store"}` —— 原 Session 阻塞工具原地取回决策 |
| Agent 按选择继续、上下文连续 | ✅ 已验证 | Agent 无需用户重述，写出结论文件：用户选择 A / **结论 OK-A** |
| 严格回复解析 | ✅ 已验证 | 修复后裸文本（"收到/你好"）判无效提示格式，仅 A/B/C+意见/STOP/DEC-ID 生效（48 项测试） |

**第二轮附带发现（幂等实证）**：第二轮决策被首个到达消息（"收到"）误采纳后，后续 "A"×4、"你好"、"已回复没收到吗" 全部被状态守卫拒绝（reply_rejected×7）——一决策仅一次有效回复在真实流量下验证。

**已知副作用（如实记录）**：第一轮恢复走的是修复前代码，Management API 注入返回成功但会话历史未见残留；新代码已加"原 agent_session_id 与活跃会话一致才注入"门禁，防止误注入同一聊天中的其他 Agent 会话。

| 项 | 状态 | 证据 |
|---|---|---|
| 原 Session 恢复（cc_connect_resume：杀进程后 --resume） | **未验证** | 需真实杀死/重建用户在用的 cc-connect 会话进程，未做破坏性测试。机制证据：`agent-sid` 实测可用 + cc-connect 原生 idle-resume（文档+二进制字符串） |
| 检查点重建（checkpoint_rebuild） | ✅ 单元验证 | 恢复包含任务上下文/决策/恢复要求（test_resumer） |

## 五、待人工配置事项

| # | 事项 | 操作 | 必要性 |
|---|---|---|---|
| 1 | MCP Server 用户级注册（cc-connect 拉起的 Agent 需要） | `claude mcp add human-decision --scope user -- python D:/WorkSpace/task-workflow/agent-manager/human_decision/mcp_server.py` | **必需**（项目级 `.mcp.json` 只对本仓库会话生效） |
| 2 | cc-connect 防冻结（重要运维事项） | ① CMD 窗口标题栏右键→属性→**取消「快速编辑模式」**；或 ② 管理员执行 `cc-connect --force daemon install --work-dir C:\Users\Administrator\.cc-connect` 装后台服务 | **必需**（否则鼠标点击冻结进程→钉钉入站流断→回复丢失，实测踩坑） |
| 3 | cc-connect 回复 hook（权威身份校验，群聊必需） | `~/.cc-connect/config.toml` 追加 `[[hooks]]`（见 README），然后 `POST /api/v1/reload` | 可选（单聊已有兜底；**群聊决策必须**） |
| 4 | 决策人白名单 | `config/adapters/hitl.yaml → human_decision.decoders` 填钉钉 user_id（单聊可留空） | 建议 |
| 5 | HITL 常驻服务 | `python agent-manager/human_decision/cli.py daemon`（建议注册系统服务/开机自启） | **必需**（无 daemon 时 MCP 工具自身轮询仍可闭环，但无超时提醒/补发） |
| 6 | `CC_MGMT_TOKEN`（.env，可选） | 留空则自动读取 `~/.cc-connect/config.toml` | 可选 |

## 六、Git 管理

- `757ae00 feat: HITL 人工决策闭环 — agent-manager/human_decision`
- `471bfaa fix: HITL 通知通道 — 钉钉官方 API 直发优先（cc-connect send 虚报成功不送达）`
- 最终提交：严格回复解析 + 本报告（见 git log）
- 未提交（有意保留）：`execution/**` 运行产物、`reports/hitl-e2e*` 测试产物、并行会话的 P11 文件（runner/monitor 等，非本次范围）
- 无凭据入库：钉钉/management token 只在内存；`.env` 保持 gitignored；测试产物不含 token
- 未推送远程（未经授权）
