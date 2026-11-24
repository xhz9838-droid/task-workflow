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

## 3. 真实 cc-connect 通道隔离 — PASS（新会话）

- 用户级 `~/.claude/settings.json` 已注册 Hook（`state=ok`）；
- 旧会话（Hook 安装前启动）不会热加载，需 `/new`；
- 2026-11-24 14:43 新会话测试：
  - `/new` 后发送裸 `A`；
  - Hook 日志 `block=true outcome=accepted`；
  - cc-connect `turn complete input_tokens=0 output_tokens=0` → **无模型 turn**；
  - 决策 `DEC-HITL-ISOLATION-FINAL-...` RESUMED。
- 普通聊天：Hook 对无 `CC_SESSION_KEY`/非 HITL prompt 放行（14:46 日志 `block=false`）；**钉钉侧普通聊天回复仍 NOT_TESTED**。

## 4. 真实钉钉决策结果（前序）

| 测试 | 结果 |
|---|---|
| 显式 DEC-ID A/B/C | **PASS**：A/B/C 三条均一次接受 |
| 单决策裸回复 | **PASS**（新会话 Hook，0 模型 tokens） |
| 已决后裸 B | 正确返回“当前没有匹配”，未串线 |
| 多待决同时存在 + 裸 B 歧义 | **NOT_TESTED** |
| C + 自定义意见 / 自然语言 | **NOT_TESTED** |
| 本轮重复回复 | **NOT_TESTED** |
| 普通聊天钉钉回复 | **NOT_TESTED**（Hook 放行逻辑已自动化/日志验证） |

## 5. 消息风暴

- `[projects.display] thinking_messages=false, tool_messages=false` 已生效并 reload；
- 用户确认复测完成，未再反馈风暴；
- 日志每轮一次 `turn complete` / 一次最终发送；未采集精确条数。

## 6. 结论

- 消息分流：**PASS（真实 cc-connect 新会话，0 模型 tokens）**；
- 安装/注册：PASS（Windows 隔离用户；macOS NOT_TESTED）；
- 旧会话需 `/new` 才加载 Hook；
- 普通聊天钉钉真实回复、多待决歧义、自定义意见、重复回复仍 NOT_TESTED；
- 最终结论：**CONDITIONAL PASS**（核心隔离已通过，剩余场景待测）。
