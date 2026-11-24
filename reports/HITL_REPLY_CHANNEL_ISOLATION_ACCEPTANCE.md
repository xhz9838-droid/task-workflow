# HITL 回复通道隔离验收（2026-11-24）

## 1. 自动化

| 范围 | 结果 |
|---|---|
| 源码全量 | **231 passed** |
| 发行版全量 | **305 passed** |
| 发行版 HITL | **110 passed** |

新增 `test_prompt_router.py`（9 项）：

- 无待决 → 普通聊天放行；
- 单待决 + 裸 A → 阻止 Agent 并接受；
- 单待决 + 普通文本 → 放行；
- 双待决 + 裸 B → 阻止并返回候选 DEC-ID；
- 显式 DEC-ID + C 自定义意见 → 阻止并接受；
- 其他 Chat 裸选项 → 不放行、不认领；
- 其他 Chat 显式 ID → 阻止并拒绝；
- 非法选项 → 阻止并提示，不启动 Agent；
- daemon 已先接受同一消息 → Hook 仍阻止 Agent（`already_handled`）。

## 2. 真实 Claude Code hook 验证

**PASS（机制验证）**：

- 临时 `--settings` 安装 `UserPromptSubmit` hook；
- 设置真实 `CC_SESSION_KEY`；
- 输入 `A`；
- 输出 `UserPromptSubmit operation blocked by hook`，无模型回复；
- 决策 `DEC-HITL-HOOK-TEST-...` 状态 `RESUMED`，回复 A。

## 3. 真实 cc-connect 通道隔离

**NOT_TESTED**：

- hook 未安装到用户级 Claude settings（按边界不擅自修改用户配置）；
- 因此没有“真实钉钉消息 → cc-connect → Claude hook 阻止 Agent”的端到端证据。
- 机制已在真实 Claude 进程中验证；激活步骤见 RCA。

## 4. 真实钉钉决策结果（前序）

| 测试 | 结果 |
|---|---|
| 显式 DEC-ID A/B/C | **PASS**：A/B/C 三条均一次接受 |
| 单决策裸回复 | **PASS（此前 live_continue 测试）** |
| 已决后裸 B | 正确返回“当前没有匹配”，未串线 |
| 多待决同时存在 + 裸 B 歧义 | **NOT_TESTED** |
| C + 自定义意见 / 自然语言 | **NOT_TESTED** |
| 本轮重复回复 | **NOT_TESTED** |

## 5. 消息风暴

- `[projects.display] thinking_messages=false, tool_messages=false` 已生效并 reload；
- 用户确认复测完成，未再反馈风暴；
- 日志每轮一次 `turn complete` / 一次最终发送；未采集精确条数。

## 6. 结论

- 消息分流机制：**实现并真实 Claude hook 验证**；
- cc-connect 端到端激活：**NOT_TESTED**；
- 最终 P0 通道隔离：**CONDITIONAL**（未激活）。
