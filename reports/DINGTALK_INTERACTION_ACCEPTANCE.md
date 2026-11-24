# 钉钉交互验收（2026-11-24）

- 结论：**自动化通过；真实钉钉多决策/消息风暴复测未完成（等待用户回复）**。
- 不得将本报告视为完整真实 E2E 通过。

## 1. D01–D06

| 编号 | 测试内容 | 自动化 | 真实钉钉 | 证据/说明 |
|---|---|---|---|---|
| D01 | 裸回复 A | PASS | **PASS** | 2026-11-23 真实 Claude Session 测试，`DEC-HITL-SESSION-...` 回复 A 被接受 |
| D02 | decision_id + A | PASS | **PASS** | 2026-11-24 真实回复 `DEC-HITL-REL-C/A/B-... A/B` 均一次接受 |
| D03 | decision_id + C + 自定义意见 | PASS | **NOT_TESTED** | 三条测试决策均以 A/B 回复，未发送 C + 自定义意见 |
| D04 | 选项 + 自定义意见 | PASS | **NOT_TESTED** | `test_reply_formats` 覆盖 `C，建议…`；真实未测 |
| D05 | 自然语言选择 | PASS | **NOT_TESTED** | `我选择 A，按第一个方案执行` 解析通过；真实未测 |
| D06 | 重复发送同一消息 | PASS | **NOT_TESTED（本轮）** | 早前显式 DEC-ID 重复回复被拒（RESUMED）；本轮未重复发送 |

## 2. 多决策并发

已创建同一聊天三条测试决策：

```text
DEC-HITL-REL-A-20261124-11591001
DEC-HITL-REL-B-20261124-11591002
DEC-HITL-REL-C-20261124-11591103
```

预期：

1. 裸 `B` → 系统提示多个候选，要求 DEC-ID；
2. `DEC-...A B`、`DEC-...B A`、`DEC-...C C 自定义意见` → 分别处理一次；
3. 重复 `DEC-...A B` → 不再次恢复。

当前状态（2026-11-24 13:39）：

- `DEC-HITL-REL-C-...` 11:59:46 收到 `DEC-... A`，一次接受；
- `DEC-HITL-REL-A-...` 13:38:34 收到 `DEC-... A`，一次接受；
- `DEC-HITL-REL-B-...` 13:39:08 收到 `DEC-... B`，一次接受；
- 三条均 `RESUMED`（`checkpoint_rebuild`，无原 Session）；
- 13:39:52 用户在所有决策已决后发送裸 `B`，系统返回“当前没有匹配的待决决策”，
  没有串到其他决策（正确的拒绝）。

真实“多个待决同时存在时裸 B 应提示 DEC-ID”**未实测**（用户先按 DEC-ID 回复完了）；
自动化 `test_multiple_fresh_unbound_requires_dec_id_with_candidates` 已通过。

## 3. 消息风暴

- 已配置 `[projects.display] thinking_messages=false, tool_messages=false`；
- `POST /api/v1/reload` 返回 `ok:true, config reloaded`；
- cc-connect 已启动并 Running。

自动化/代码证据：DingTalk legacy 模式下，thinking/tool 事件的逐条发送被 display 开关关闭；
最终回复不受影响。

真实消息条数：**用户确认“已完成”测试，未再反馈风暴**；
cc-connect 日志对 11:57 / 13:38 / 13:39 的每轮只有一次 `turn complete` 与一次
`slow agent send`（最终回复），没有逐条 thinking/tool 发送记录。
**未采集精确发送条数**，因此不断言“从 N 条降到 M 条”。

## 4. 多用户

自动化覆盖：身份白名单、跨聊天拒绝、显式 DEC-ID 跨聊天拒绝。
真实多用户（两个钉钉账号）**NOT_TESTED**，当前环境只有一个已授权决策人。

## 5. Session 恢复

| 路径 | 结果 | 证据 |
|---|---|---|
| `live_continue` | **PASS** | 2026-11-23 真实 Claude 后台 Session 输出 `SESSION_RESUME_OK` |
| `checkpoint_rebuild` | **PASS（新 Session）** | 恢复包 + 新 Session 输出 `CHECKPOINT_RESUME_OK` |
| `cc_connect_resume` | **NOT_TESTED** | 无独立 cc-connect 测试会话 |

## 6. 自动化测试结果

| 仓库/范围 | 结果 |
|---|---|
| 源码全量 | **222 passed** |
| 发行版全量 | **293 passed** |
| 发行版 HITL | **101 passed** |

## 7. 消息数量/重试/恢复统计

当前没有 cc-connect 发送条数的结构化指标；本轮只能确认：

- 修复前日志存在大量 thinking/tool 事件与 `falling back` 警告；
- 修复后 `display` 配置已加载；
- 未观察到无界重试代码路径（cc-connect 发送失败有重试上限，Workflow 不在发送链路内）；
- Agent 启动/恢复次数以决策表为准：三条新测试决策均未触发恢复。

因此不提供虚构的“消息数从 N 降到 M”数字。
