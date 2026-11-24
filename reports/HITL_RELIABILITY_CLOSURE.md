# HITL 可靠性收尾（2026-11-24）

## 1. 最终结论

**CONDITIONAL PASS**

- 单决策裸 A/B/C：代码与真实回复均通过（生产决策创建时自动绑定 Chat）。
- 多决策：显式 DEC-ID 一次接受；裸选项歧义自动化通过，真实歧义提示未测。
- 幂等/一次恢复：唯一约束 + 原子状态，测试通过。
- **通道隔离**：已实现 Claude Code `UserPromptSubmit` 路由，真实 Claude hook 验证可阻止模型 turn；
  但**未在用户级 settings 激活**，真实 cc-connect 端到端隔离 NOT_TESTED。

## 2. P0 逐项

| P0 标准 | 状态 | 说明 |
|---|---|---|
| 单决策只需 A/B/C | **PASS** | 绑定到当前 Chat 的唯一待决即可裸回复；真实 live A 通过 |
| 多决策才要求 DEC-ID | **PASS（逻辑）** | 候选 >1 返回候选列表；真实裸 B 歧义未测 |
| HITL 回复不再触发普通 Agent | **CONDITIONAL** | `prompt_router.py` + 真实 Claude hook 验证阻止模型 turn；cc-connect 端未激活 |
| 一条决策只接受一次 | **PASS** | `(decision_id,msg_id)` 唯一 + 状态守卫；重复测试通过 |
| 只恢复一次 | **PASS** | 状态机 RESUMING/RESUMED 守卫；测试通过 |

## 3. 关键修改

| 文件 | 内容 |
|---|---|
| `reply_handler.py` | 候选只取本聊天已绑定待决；未绑定不参与裸选项；歧义提示候选 DEC-ID + 任务/主题；有效回复才绑定；跨聊天拒绝 |
| `reply_parser.py` | 标点/自然语言选择；DEC-ID + C 自定义意见 |
| `prompt_router.py`（新增） | Claude UserPromptSubmit 分流：HITL → exit 2 阻止 Agent；普通聊天放行 |
| `test_prompt_router.py`、`test_reply_binding.py`、`test_reply_formats.py` | 覆盖单/多候选、跨 Chat、幂等、路由 |

## 4. 测试与提交

| 仓库 | 测试 | 最新提交 |
|---|---|---|
| 源码 | **230 passed** | `f2020e8` |
| 发行版 | **301 passed / HITL 109** | `8e64231` |

本轮改动已提交到本地 `main` / `master`；未 push。

## 5. 配置副作用

- `~/.cc-connect/config.toml` 增加 `[projects.display] thinking_messages=false/tool_messages=false`；
- 修复并发编辑损坏的 `work_dir`；备份 `config.toml.bak.20261124*`；
- cc-connect 已启动并 Running；`/api/v1/reload` 成功；
- 未修改用户级 Claude settings、MCP 配置、`.home`。

## 6. 未完成 / 风险

1. **激活 UserPromptSubmit hook**（唯一缺口；需用户授权写 Claude settings）。
2. 真实 cc-connect 通道隔离 E2E（激活后一条决策消息不应启动模型 turn）。
3. 真实多待决裸 B 歧义、C 自定义意见、自然语言、重复回复。
4. `cc_connect_resume`。
5. 多用户/群聊身份隔离。
6. 消息条数定量统计。
7. cc-connect 仍会启动 Claude 进程（hook 仅阻止模型 turn）；若要求进程也不启动，需 cc-connect 补丁或独立机器人。

## 7. 建议

- 批准在用户级 Claude settings 添加 hook 后，做一条真实钉钉测试：
  - 单待决发 `A` → 直接处理，无 Agent 回复；
  - 双待决发 `B` → 歧义提示，无 Agent 回复；
  - 普通聊天“你好” → 正常 Agent 回复。
- 通过后再扩大团队试点；否则只维持当前“决策正确但 Agent 会多跑一轮”的 CONDITIONAL 状态。
