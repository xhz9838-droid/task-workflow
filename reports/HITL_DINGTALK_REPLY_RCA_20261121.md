# HITL 钉钉回复未接收 — 故障诊断与修复报告

- 日期：2026-11-21
- 项目/任务：jeebootx / 3442
- 决策：DEC-3442-16301801
- 结论：**回复已真实到达系统，但被错误路由到另一个已 RESUMED 的决策；原决策未收到。已修复匹配逻辑并恢复原决策。**
- 端到端验证：**PARTIAL**（有真实入站消息证据 + 修复后重放同一真实消息；未做修复后的全新回调验证）

---

## 1. 真实结论（根因分类）

| 分类 | 判定 | 说明 |
|---|---|---|
| A. 钉钉没收到 | ❌ 排除 | cc-connect 16:32:04 / 16:35:14 收到 `B` |
| B. cc-connect 没收到 | ❌ 排除 | cc-connect 日志 `message received` 且进入 `processing message` |
| C. 没路由到原 Session | ⚠️ 部分 | 决策创建时无 Session/聊天绑定，无法定位原会话 |
| **D. 收到但未关联原决策** | ✅ **主因** | watch 扫描到了 `B`，却匹配到 `DEC-3413-11501101`（RESUMED）并拒绝 |
| E. B 解析/持久化失败 | ❌ 排除 | `B` 解析为 option 正常；只是落在错误决策上 |
| F. 已持久化但 CC 未感知 | ❌ 排除 | 原决策无任何回复记录 |
| G. 300s 超时提前结束 | ❌ 排除 | 第二次 `B` 在 16:35:14，早于 16:35:21 `tool_suspended` 7 秒；超时不丢弃合法回复 |

补充根因：

- **根因 1（主因）**：`DEC-3442-16301801` 创建时 `cc_project`/`cc_session_key`/`session_id` 全空。
- **根因 2**：`_resolve_decision` 在“无绑定待决决策”时回退到同会话最近**已决**决策，
  把 `B` 记到 `DEC-3413-11501101` 上并拒绝（“决策状态 RESUMED 不可回复”）。
- **根因 3**：HITL daemon 未运行（锁文件残留 PID 21696），只有 MCP 工具内的 300s 轮询在扫消息；
  工具挂起后没有任何消费者。
- **附带缺陷**：`SessionResumer._ROOT` 多算一级目录，恢复包写到 `D:/WorkSpace/execution/...`
  而不是工作流根。

---

## 2. 时间线与证据

| 时间 | 事件 | 证据 |
|---|---|---|
| 16:30:18 | 创建决策，`cc_*`/`session_id` 为空 | `human_decisions` 行；`created` 事件 |
| 16:30:19 | 钉钉直发成功，进入 WAITING_REPLY | `notified_at`；`status → WAITING_REPLY` |
| 16:32:04 | 用户钉钉回复 `B`（msg `msgSjO96fwVevu0Zl0aZW1QgA==`） | `~/.cc-connect/logs/cc-connect.log`；会话历史 `personal_1899030b.json` |
| 16:32:04 | cc-connect 按普通消息投给 Agent，`NO_REPLY` | 同一日志 `processing message` / `turn complete` |
| 16:32:05 | HITL watch 处理 `B`，匹配到 `DEC-3413-11501101` 并拒绝 | `decision_replies` 中 `4938bde04fd446514cb6cc6f`，`reject_reason=决策状态 RESUMED 不可回复` |
| 16:35:14 | 用户再次回复 `B`（msg `msgeUGwn+osqxCsdIz9Pi9r+w==`） | 同上 |
| 16:35:15 | 再次被记到 `DEC-3413` 并拒绝 | `decision_replies` 中 `f15a51750f9458c1289fdedb` |
| 16:35:21 | MCP 300s 到期，`tool_suspended`；决策仍 WAITING_REPLY | `decision_events` |
| 16:30:20 | 旧决策 `DEC-3657` 收到提醒，提醒时间**晚于** 3442 通知 1 秒 | `reminded_at=2026-11-21T16:30:20`；恢复重放时因此产生歧义，已修正匹配锚点 |

`msgId` 指纹已复核：`_fingerprint("personal_1899030b.json","s1","2026-11-21T16:32:04.2241209+08:00","B")`
= `4938bde04fd446514cb6cc6f`，与数据库拒绝记录完全一致 → 证明该消息确实进入过 HITL。

daemon 证据：

- `agent-manager/logs/hitl-daemon.lock` 残留 `21696`，`tasklist` 无此进程；
- supervisor 日志最后一行停在 2026-11-17；
- 因此 16:30–16:35 的扫描来自 MCP `wait_for_decision` 内部 `poll_once()`，不是 daemon。

---

## 3. 代码位置（修复前）

| 位置 | 问题 |
|---|---|
| `decision_manager.py:112-114` | 只读 `CC_PROJECT`/`CC_SESSION_KEY`，拿不到就留空，无兜底绑定 |
| `reply_handler.py:_resolve_decision` | 同会话无绑定待决时，回退到已决决策（RESUMED），造成串决策 |
| `reply_handler.py:_time_anchor` | 原用 `reminded_at` 优先，旧决策的提醒会抢新决策的回复 |
| `session_resumer.py:_ROOT` | `dirname` 三层 → `D:/WorkSpace`，恢复包写错目录 |
| `cli.py` daemon | 锁的陈旧接管逻辑正确，但进程实际未运行 |

---

## 4. 修复内容

| 文件 | 修复 |
|---|---|
| `human_decision/hitl_config.py` | 新增 `discover_chat_binding()` / `project_for_session_key()`：无 CC_* 时从 cc-connect 会话文件推断私聊绑定，优先匹配配置的 `dingtalk_user_id` |
| `human_decision/decision_manager.py` | 创建决策时自动绑定默认私聊会话（`binding_auto` 事件）；自动绑定不猜测 `session_id` |
| `human_decision/reply_handler.py` | 重写匹配：**先待决后已决**；未绑定待决自动绑定；多个待决按通知时间择新（间隔 ≥1h）；间隔过近要求显式 `DEC-ID`；提醒不再改变匹配优先级；**超过 12h 的未绑定决策不自动认领**；未匹配回复写 `reply_unmatched` 事件 |
| `human_decision/session_resumer.py` | `_ROOT` 修正为工作流根（两级 dirname） |
| 运行态 | 以新代码启动 HITL daemon（PID 31384），接管陈旧锁 |

未改动：DAG、Agent Manager、SQLite schema、决策状态机、3442 执行状态。

---

## 5. 回归测试

新增 `agent-manager/human_decision/tests/test_reply_binding.py`（12 项）：

1. 私聊绑定发现优先配置用户
2. 无明确用户时不猜测聊天绑定
3. 无 CC_* 环境时创建决策自动绑定
4. 单个未绑定决策的回复可接收并绑定
5. **同会话已有 RESUMED 决策时不串决策**（复现事故）
6. 多个未绑定决策按通知时间择新
7. 旧决策提醒不抢新决策回复
8. 通知时间接近时要求显式 DEC-ID
9. 超龄未绑定决策不自动认领
10. 超龄决策仍可通过显式 DEC-ID 回复
11. 超时挂起后的迟到回复仍接收
12. 默认恢复包落在工作流根 `execution/` 下

全量测试：**189 passed**（修复前 177 + 新增 12）。

---

## 6. 原决策恢复结果

使用**真实到达的那条消息**（16:32:04，`msg_id=4938bde04fd446514cb6cc6f`）重放：

| 项目 | 结果 |
|---|---|
| 决策 | `DEC-3442-16301801` |
| 选择 | `B` |
| 回复人 | 徐弘祖（17248148409976157） |
| 回复持久化 | ✅ `decision_replies` accepted=1，source=watch |
| 状态 | WAITING_REPLY → DECISION_RECEIVED → RESUMED |
| 聊天绑定 | 自动绑定 `personal` / `dingtalk:d:...:17248148409976157` |
| execution_id | 17（已回填） |
| 恢复方式 | `checkpoint_rebuild`（原交互 Session 无 cc-connect agent_session_id，不伪造） |
| 恢复包 | `D:/WorkSpace/task-workflow/execution/jeebootx/3442/human-decision/resume-packet-DEC-3442-16301801.md` |
| 重复决策 | 未创建 |

未标记 `COMPLETED`：`COMPLETED` 表示 Agent 已完成后续工作，本次只恢复到“决策已返回、待继续执行”。

---

## 7. 端到端验证结论

| 环节 | 状态 | 证据 |
|---|---|---|
| 钉钉发送成功 | PASS | 16:30:19 通知 |
| 钉钉收到用户回复 | PASS | cc-connect 日志 + 会话历史 |
| CC 收到消息 | PASS | cc-connect `processing message` |
| HITL 看到消息 | PASS | 拒绝记录 / 指纹一致 |
| HITL 关联原决策 | **修复后 PASS（重放）** | 真实消息重放后 accepted |
| 原 Session 恢复 | PARTIAL | 决策已 RESUMED + 恢复包；原交互 Session 无自动 resume 标识 |
| 修复后全新钉钉回调 | **NOT_TESTED** | 未创建新决策、未要求用户再次确认；按约束不做 |

因此：**不宣称“修复后端到端已通过”**。可宣称“主因已定位并修复，真实消息重放验证通过”。

---

## 8. 运维与遗留

1. **必须重启已有 Claude 会话 / MCP Server**：运行中的 MCP 进程仍是旧代码；新 daemon 已用新代码启动，
   但旧 MCP 的 300s 轮询仍可能在过渡期抢先错误落库。
2. **DEC-3657-17173201** 仍为 WAITING_REPLY（11-20 创建，已提醒）。修复后超过 12h 的未绑定决策
   不再被自动认领，普通 `B` 不会落进去；显式 `DEC-3657-... B` 仍可回复。建议在禅道侧确认后关闭/作废该决策。
3. **恢复包错位遗留**：`D:/WorkSpace/execution/jeebootx/3442/human-decision/` 是修复前错写的副本
   （删除操作被权限拦截，未强删）；`3413`、`3438` 目录为历史同类产物。正式清理需你确认。
4. cc-connect 仍会把 `B` 当普通 Agent 消息处理（返回 NO_REPLY），这是其入口行为；HITL 通过会话文件并行消费，不影响。
5. 未提交 Git、未改全局 Skill、未影响 3442 的 B2/C2、未派发 Agent、未触发 Jenkins。

---

## 9. 验收清单

- [x] 真实根因（D + 未绑定 + daemon 未运行）
- [x] 代码位置与日志证据
- [x] 修复文件清单
- [x] 新增 12 项回归测试
- [x] 全量 189 passed
- [x] 原决策恢复（B 已持久化，RESUMED，恢复包正确）
- [ ] 修复后全新钉钉回调端到端（未做，不宣称）
