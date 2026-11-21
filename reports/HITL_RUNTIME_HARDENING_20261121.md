# HITL 运行环境收尾与可靠性验收报告

- 日期：2026-11-21
- 依据：`reports/HITL_DINGTALK_REPLY_RCA_20261121.md`
- 范围：旧 MCP 消费者清理、daemon 生命周期、DEC-3657 处置、恢复目录核对、回归测试
- 未做：未提交 Git、未同步全局 Skill、未发布安装包、未触发 Jenkins、未派发 Agent、未改 3442 节点记录

---

## 1. 旧 MCP Server 清理

### 1.1 清理前

| PID | 启动时间 | 父进程 | 命令行 | 代码版本 |
|---|---|---|---|---|
| 27812 | 09:31:16 | claude.exe 32276 | `python -I D:\WorkSpace\task-workflow\agent-manager\human_decision\mcp_server.py` | 旧 |
| 31392 | 12:33:19 | claude.exe 1932（本会话） | `python agent-manager/human_decision/mcp_server.py` | 旧 |
| 28192 | 15:28:55 | claude.exe 26872 | `python -I D:\WorkSpace\task-workflow\agent-manager\human_decision\mcp_server.py` | 旧 |

三个进程均启动于修复前（修复代码 16:48–17:06 落盘），全部加载旧版内存代码。

### 1.2 加载路径确认

| 来源 | 实际路径 | 是否旧副本 |
|---|---|---|
| 源码（唯一开发源） | `D:\WorkSpace\task-workflow\agent-manager\human_decision\mcp_server.py` | 修复后 |
| 用户级 MCP 注册 `~/.claude.json` | `python -I D:\WorkSpace\task-workflow\agent-manager\human_decision\mcp_server.py` | 指向源码 |
| 项目级 `.mcp.json` | `python agent-manager/human_decision/mcp_server.py`（相对仓库根） | 指向源码 |
| 全局 Skill `~/.claude/skills/zentao-dev-workflow/` | 只有 SKILL.md/references/templates，**无 mcp_server.py** | 无旧副本 |

结论：不存在“全局安装版覆盖源码”的问题；新会话只要从上述注册启动，就加载修复后的源码。

### 1.3 清理动作

只终止上述 3 个 `mcp_server.py` 进程，未动任何 `claude.exe` 或其它 Python：

```
taskkill /PID 27812 /F
taskkill /PID 31392 /F
taskkill /PID 28192 /F
```

清理后复核：`python.exe` 且命令行含 `mcp_server.py` 的进程数为 **0**（查询时排除 PowerShell/Bash 自身命令）。

### 1.4 新进程加载验证

以全新 Python 进程直接加载源码：

- `reply_handler.__file__` = `D:\WorkSpace\task-workflow\agent-manager\human_decision\reply_handler.py`
- `ReplyHandler._AUTO_BIND_MAX_AGE_SECONDS` = `43200`（12h 修复已生效）
- `mcp_server.build_server()` = OK

当前会话的 human-decision MCP 工具已随旧进程退出（连接断开是预期结果）；新 Claude Code 会话会按注册路径重新拉起，加载修复代码。

### 1.5 多消费者竞争

- 清理后只剩 **1 个常驻消费者：HITL daemon**。
- 新会话的 MCP 在 `wait_for_decision` 期间会在进程内轮询（设计如此），即“daemon + 等决策的 MCP”两个消费者。
- 两者运行同一版代码；回复按 `(decision_id, msg_id)` 唯一约束与状态原子转移保证幂等，不会重复消费。
- 旧/新混跑才会出现的“旧代码先错误落库、新代码被 `_mark_seen` 跳过”风险，已随旧 MCP 全部退出而消除。

---

## 2. HITL daemon 运行保障

### 2.1 当前状态

| 项 | 值 |
|---|---|
| supervisor | PID **12988**，`pythonw.exe ...\daemon_supervisor.py`，17:20:12 启动 |
| daemon | PID **31044**，`pythonw.exe -u ...\cli.py daemon --interval 3`，父进程=12988 |
| supervisor 锁 | `agent-manager/logs/hitl-supervisor.lock` = `12988`（有效） |
| daemon 锁 | `agent-manager/logs/hitl-daemon.lock` = `31044`（有效） |
| 代码路径 | `D:\WorkSpace\task-workflow\agent-manager\human_decision\{daemon_supervisor.py,cli.py}` |
| 代码时间 | `cli.py` 17:18:45 < daemon 启动 17:20:12 → 已加载最新修复 |
| 自启 | HKCU Run 已有 `hitl-daemon` → `pythonw.exe ...\daemon_supervisor.py` |

此前会话内后台启动的 daemon（31384）已终止，改为 detached supervisor + daemon，生命周期不再绑定本 Claude 会话。

### 2.2 生命周期评估

现有能力已足够，无需新增框架：

- supervisor 单实例锁；daemon 异常退出 10s 后重启；
- daemon 自身锁防重复；退出码 2（已有实例）时 60s 重试；
- HKCU Run 实现登录自启（无需管理员）；
- 日志：`logs/hitl-supervisor.log`、`logs/hitl-daemon.out.log`。

残余风险：

- **HKCU Run 只在用户登录时拉起 supervisor**；登录期间 supervisor 若被杀，没有外部看门狗。
- 若需要“supervisor 自身崩溃也自动恢复”，最轻量替代是 Windows 任务计划程序（用户级、登录触发，重复间隔 1 分钟）：
  ```
  schtasks /Create /TN "hitl-daemon-supervisor" /SC ONLOGON /RL LIMITED ^
    /TR "\"C:\Users\Administrator\AppData\Local\Programs\Python\Python313\pythonw.exe\" \"D:\WorkSpace\task-workflow\agent-manager\human_decision\daemon_supervisor.py\""
  ```
  **本轮未注册**（按约束不修改系统任务）。
- HKCU Run 写的是绝对路径；工作流仓库迁移后需同步更新。

---

## 3. DEC-3657 处置

### 3.1 有效性核查

| 项 | 结果 |
|---|---|
| 决策 | `DEC-3657-17173201` |
| 项目/任务 | `subcontract-eval` / `3657` |
| execution_id / session_id / cc 绑定 | 全部为空 |
| 回复记录 | 无 |
| 本地任务状态 | `RESOLVED`（用户 2026-11-21 确认 #3657 已解决；blocker L3-001 resolved） |
| 是否有替代决策 | 无，仅此一条 |
| 恢复价值 | 无：任务已闭环，决策仅为当时“停标选不到下一审批人发生在哪个环节”的确认 |

### 3.2 处置

使用现有合法流转（不删历史）：

```
WAITING_REPLY → DECISION_TIMEOUT
event: expired_stale  {"reason":"#3657 已解决，决策过期"}
last_error: "任务 #3657 已解决；决策过期（EXPIRED），不再等待回复"
```

说明：

- 状态机没有 `CANCELLED`；`DECISION_TIMEOUT` 是现有语义上的 EXPIRED，且 `timeout_handler` 对已超时决策跳过，不再重复提醒。
- 该决策仍会出现在 `list_waiting()`（既有设计：超时仍允许迟到回复），但 12h 自动认领规则会排除它；普通 `B` 不会落进去。显式 `DEC-3657-... B` 仍可回复（保留迟到回复语义）。
- 如需彻底移出等待集合，唯一剩余的合法流转是 `DECISION_TIMEOUT → REJECTED`；本轮未做，避免把“过期”误标成“用户拒绝”。

---

## 4. 恢复目录检查

### 4.1 3442（正确 vs 错误）

| 位置 | 文件 | 大小 | 状态 |
|---|---|---|---|
| `task-workflow/execution/jeebootx/3442/human-decision/`（正确） | decision JSON | 2701 B | `RESUMED`，含 execution_id/绑定 |
| 同上 | resume-packet.md | 7485 B | **含 task-context.md 等执行上下文** |
| `D:/WorkSpace/execution/jeebootx/3442/human-decision/`（错误） | decision JSON | 2672 B | `DECISION_RECEIVED`，旧快照 |
| 同上 | resume-packet.md | 1491 B | 无执行上下文（“无执行状态文件”） |

结论：正确目录完整可用；错误目录是修复前 `_ROOT` 错位的旧快照，代码已不再读取。

### 4.2 3413 / 3438

- `task-workflow/execution/jeebootx/3413/human-decision/`、`.../3438/human-decision/` **不存在**。
- `D:/WorkSpace/execution/jeebootx/3413|3438/human-decision/` 是**唯一副本**：
  - 3413：decision 3572 B + packet 1749 B
  - 3438：decision 2190 B + packet 1190 B

### 4.3 清理方案（未执行）

1. 将 `D:/WorkSpace/execution/jeebootx/{3413,3438}/human-decision/` 复制到
   `task-workflow/execution/jeebootx/{3413,3438}/human-decision/`（保留历史恢复素材）。
2. 复核 3442：正确目录已完整，错误目录为旧快照。
3. 经你确认后删除 `D:/WorkSpace/execution/jeebootx/{3442,3413,3438}`；
   删除操作此前被权限拦截，本轮未强删。
4. 风险：错误目录在工作流仓库之外，可能被误认为有效状态；但 `_ROOT` 已修正，现有代码不会读写它们。目录内为决策文本，无凭据。

---

## 5. 回归测试

| 范围 | 结果 |
|---|---|
| 回复匹配 / 会话绑定 / 多决策歧义 / 已决不抢待决 / 12h 过期 / 迟到回复 / 恢复包根目录 | `test_reply_binding.py` **12 passed** |
| daemon 单消费者与锁恢复 | `test_daemon_lock.py` **3 passed** |
| 决策生命周期 + Session/checkpoint 恢复 | `test_manager.py` + `test_resumer.py` **13 passed** |
| 全量 | **192 passed**（1 warning，既有 pytest 收集提示） |

新增 daemon 锁测试时发现并修复一个真实缺陷：
`cli._release_daemon_lock` 在 Windows 上“文件句柄未关闭就 unlink”会静默失败，导致正常退出残留锁文件。
已改为先关闭句柄再删除，并由 `test_stale_lock_is_taken_over` / `test_release_only_own_lock` 锁定行为。

---

## 6. 验收结论（逐项）

1. **旧 MCP Server 是否全部退出？**
   **是。** 只终止了 3 个旧 `mcp_server.py`（27812/31392/28192），未动 Claude 主进程；复核残留为 0。

2. **当前 MCP Server 是否加载修复代码？**
   **当前没有运行中的 MCP Server**（已按要求退出）。全新进程验证：
   - 源码路径正确、`_AUTO_BIND_MAX_AGE_SECONDS=43200`、`build_server()` OK；
   - 新 Claude 会话将按同一注册路径拉起并加载修复代码。

3. **daemon 是否具有可靠生命周期保障？**
   **是（轻量方案）。** supervisor 12988 + daemon 31044 已 detached 运行，锁有效；
   HKCU Run 已存在，登录自启。残余风险：登录期间 supervisor 自身无外部看门狗；
   如需该级别保障，可用任务计划程序（方案已给出，未注册）。

4. **DEC-3657 是否已妥善处置？**
   **是。** 已确认无恢复价值；`WAITING_REPLY → DECISION_TIMEOUT`，写 `expired_stale` 事件，
   历史保留；不再参与普通回复自动认领。

5. **恢复目录是否正确？**
   **3442 正确目录完整可用**；错误目录为旧快照。
   **3413/3438 只有错误位置副本**，清理/迁移方案已给出，未强删。

6. **全量测试结果？**
   **192 passed**（新增 15 项：12 回复绑定 + 3 daemon 锁；含既有 manager/resumer）。

7. **仍需真实钉钉决策验证的项：**
   - 修复后**全新** L3 决策：钉钉通知 → 用户回复 → 自动绑定 → 接受 → 原 Session/checkpoint 恢复；
   - 新 MCP 会话（修复代码）与 daemon 并存时的真实消息消费；
   - Windows 注销/重启后 supervisor 自启与 daemon 接管；
   - 以上未做，不宣称端到端已通过。

---

## 7. 本轮未做

- 未提交 Git、未同步全局 Skill、未发布安装包；
- 未触发 Jenkins、未派发 Agent、未修改 3442 已完成节点与执行记录；
- 未创建新决策制造测试数据；
- 未修改系统服务/任务计划程序。
