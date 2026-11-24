# HITL 回复解析 RCA（2026-11-24）

- 结论：首次失败的主因是**多待决决策下旧路由回退到已决决策 3413**；不是钉钉消息截断。
- 已修复：严格唯一匹配、显式 DEC-ID 精确绑定、聊天绑定校验、解析格式扩展。
- 真实钉钉多决策复测：**NOT_TESTED（三条测试决策已发出，等待用户回复）**。

## 1. 故障样本 A：第一次 B 未关联 3442

### 实测证据（2026-11-21）

- 3442 决策创建时 `cc_session_key` 为空（交互式 Session 创建）。
- 3657 决策仍为 WAITING_REPLY，且 16:30:20 收到过提醒。
- 3413 决策已 RESUMED，但绑定同一钉钉会话。
- 16:32:05 与 16:35:15 两条原始 `B` 都被记录到 `DEC-3413-11501101`，拒绝原因：
  `决策状态 RESUMED 不可回复`。
- 3442 的 accepted `B` 记录时间是 16:54:24，来自修复后的**真实消息重放**；
  数据库中没有“第二条原始 B 自动成功”的证据。若 UI 显示第二次成功，可能是后续消息/恢复动作，
  不能归因于旧代码的第二次自动匹配。

### 旧代码为什么指向 3413

旧 `ReplyHandler._resolve_decision`：

```python
bound = [d for d in waiting if d.cc_session_key == chat_session_key]
if len(bound) == 1: return bound[0]
# 无绑定待决 → 回退到同聊天最近“已决”决策
decided = [d for d in store.list(50)
           if d.cc_session_key == chat_session_key and not d.is_waiting]
return decided[0] if decided else None
```

3442 未绑定、3657 也未绑定 → `bound` 为空 → 回退到已决的 3413。
这不是“3657 抢了 3442”，而是**旧逻辑拿了一个已决决策做兜底**。

### 3657 的影响

3657 是 WAITING_REPLY，且提醒时间 16:30:20 晚于 3442 通知时间 1 秒。
旧逻辑按“提醒时间”排序时会让 3657 成为最新；但 3657 同一时间也未被绑定。
两个未绑定决策并存 → 不应自动猜测。

## 2. 修复后的路由规则

`reply_handler._resolve_decision`：

1. 显式 `DEC-ID` → 精确查找；不存在的 ID 只提示该 ID，不展示其他决策。
2. 同聊天候选 = 本聊天已绑定待决 + 有效未绑定待决（>12h 未绑定不自动认领）。
3. 候选唯一 → 使用；候选 >1 → **不猜测**，提示候选 DEC-ID。
4. 无待决时才用已决记录做“重复回复”提示。
5. 显式 DEC-ID 若绑定了其他聊天 → 拒绝（CLI 运维入口除外）。
6. 只有身份/选项校验通过后才建立聊天绑定，避免未授权回复抢先绑定。

对应测试：`test_sample_a_first_reply_routes_to_newest_not_resumed`、
`test_multiple_fresh_unbound_requires_dec_id_with_candidates`、
`test_explicit_dec_id_from_other_chat_rejected`。

## 3. 故障样本 B/C：`💭 The user sent "B"` / `"DEC`

### 原始消息是否完整

cc-connect 会话历史中保存的是完整消息：

```text
A
DEC-HITL-E2E-20261123-14403301 A
```

`💭 The user sent "DEC` 是 **cc-connect 的 thinking 显示文本被截断**，
不是原始消息被截断，也不是 HITL 解析器只收到 `DEC`。

证据：

- `~/.cc-connect/sessions/personal_1899030b.json` 的 user 消息完整；
- `~/.cc-connect/logs/cc-connect.log` 的 `content_len=32`（DEC-ID + A）；
- HITL `decision_replies.raw_text` 也是完整文本。

### 为什么变成思考消息

cc-connect 把每条钉钉消息都当普通聊天输入，Agent 会回复“The user sent ...”，
再经 legacy progress 逐条发送。详见 `DINGTALK_MESSAGE_STORM_RCA.md`。
HITL watcher 只是旁路读取，不会阻止 cc-connect 跑这轮 Agent。

## 4. 解析器修复

`reply_parser.parse_reply` 新增：

- 选项 + 标点：`C，建议…` / `B: 同意` / `A、方案一`；
- 自然语言明确选择：`我选择 A，按第一个方案执行。` / `选择 C，但是先不要部署。`；
- `DEC-ID C 自定义意见` 与 `DEC-ID C，自定义` 均提取三部分；
- 不把“我觉得 A 不行”这类任意字母当选择，仍要求澄清。

对应测试：`test_reply_formats.py` 12 项。

## 5. 真实复测状态

已创建三条受控测试决策（同一钉钉聊天，均 WAITING_REPLY）：

```text
DEC-HITL-REL-A-20261124-11591001
DEC-HITL-REL-B-20261124-11591002
DEC-HITL-REL-C-20261124-11591103
```

等待用户按 `docs` 的 D01–D06 发送真实回复；本轮**未收到回复**，
因此真实钉钉解析通过不能标记为 PASS。
