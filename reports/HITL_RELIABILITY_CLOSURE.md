# HITL 可靠性收尾（2026-11-24）

## 1. 最终结论

**CONDITIONAL PASS**

- 单决策裸 A/B/C：代码与真实回复均通过（生产决策创建时自动绑定 Chat）。
- 多决策：显式 DEC-ID 一次接受；裸选项歧义自动化通过，真实歧义提示未测。
- 幂等/一次恢复：唯一约束 + 原子状态，测试通过。
- **通道隔离**：已实现 Claude Code `UserPromptSubmit` 路由，并已合并到用户级
  `~/.claude/settings.json`；真实 Claude hook 验证可阻止模型 turn。
  但已存在的 cc-connect Agent 进程在安装前启动、不会热加载 Hook；需 `/new` 后复测。

## 2. P0 逐项

| P0 标准 | 状态 | 说明 |
|---|---|---|
| 单决策只需 A/B/C | **PASS** | 绑定到当前 Chat 的唯一待决即可裸回复；真实 live A 通过 |
| 多决策才要求 DEC-ID | **PASS（逻辑）** | 候选 >1 返回候选列表；真实裸 B 歧义未测 |
| HITL 回复不再触发普通 Agent | **CONDITIONAL** | Hook 已安装并验证；现有 cc-connect 会话是安装前启动的旧进程，需 `/new` 新会话复测 |
| 一条决策只接受一次 | **PASS** | `(decision_id,msg_id)` 唯一 + 状态守卫；重复测试通过 |
| 只恢复一次 | **PASS** | 状态机 RESUMING/RESUMED 守卫；测试通过 |

## 3. 关键修改

| 文件 | 内容 |
|---|---|
| `reply_handler.py` | 候选只取本聊天已绑定待决；未绑定不参与裸选项；歧义提示候选 DEC-ID + 任务/主题；有效回复才绑定；跨聊天拒绝 |
| `reply_parser.py` | 标点/自然语言选择；DEC-ID + C 自定义意见 |
| `prompt_router.py`（新增） | Claude UserPromptSubmit 分流：HITL → exit 2 阻止 Agent；普通聊天放行 |
| `scripts/hitl_hook.py`（新增） | 幂等合并/卸载/状态检查用户级 settings |
| `scripts/install.sh` | 默认安装/升级注册 Hook；`--check` 显示状态；`--uninstall` 只删自身 |
| `test_prompt_router.py`、`test_reply_binding.py`、`test_reply_formats.py`、`test_install_flags.py` | 覆盖单/多候选、跨 Chat、幂等、路由、安装/升级/卸载 |

## 4. 测试与提交

| 仓库 | 测试 | 最新提交 |
|---|---|---|
| 源码 | **231 passed** | 待提交 |
| 发行版 | **305 passed / HITL 110** | 待提交 |

本轮改动已提交到本地 `main` / `master`；未 push。

## 5. 配置副作用

- `~/.cc-connect/config.toml` 增加 `[projects.display] thinking_messages=false/tool_messages=false`；
- 修复并发编辑损坏的 `work_dir`；备份 `config.toml.bak.20261124*`；
- cc-connect 已启动并 Running；`/api/v1/reload` 成功；
- 用户级 `~/.claude/settings.json` 已合并 `UserPromptSubmit` Hook（备份保留，其他 keys 未动）；
- 发行版 `install.sh` 已集成 Hook 安装/升级/卸载与状态检查。

## 6. 未完成 / 风险

1. **真实 cc-connect 新会话隔离复测**：已存在的 Agent 进程在 Hook 安装前启动，不会热加载；
   14:25 的单决策测试仍跑了模型 turn。需要 `/new` 新建会话后复测。
2. 真实多待决裸 B 歧义、C 自定义意见、自然语言、重复回复。
3. `cc_connect_resume`。
4. 多用户/群聊身份隔离。
5. 消息条数定量统计。
6. macOS 安装/升级未真机验证。
7. cc-connect 仍会启动 Claude 进程（Hook 仅阻止模型 turn）；若要求进程也不启动，需 cc-connect 补丁或独立机器人。

## 7. 建议

- 先在钉钉发送 `/new`，再对 `DEC-HITL-ISOLATION-NEWSESSION-20261124-14360901` 发送裸 `A`：
  - 预期决策 RESUMED、钉钉收到回执、无模型 turn；
- 再发普通聊天“你好”验证放行；
- 通过后扩大到双待决歧义测试，再评估团队试点。
