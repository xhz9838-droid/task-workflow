# HITL 真实通道隔离 E2E（2026-11-24）

## 1. 已激活

- 用户级 `~/.claude/settings.json` 已注册 `UserPromptSubmit` → `prompt_router.py`；
- 状态检查 `state=ok`；
- 真实 Claude Code 临时 `--settings` 测试通过（见 `HITL_REPLY_CHANNEL_ISOLATION_ACCEPTANCE.md`）。

## 2. 关键发现：已存在的 cc-connect 会话不会热加载 Hook

2026-11-24 14:25 测试（单决策 `DEC-HITL-ISOLATION-SINGLE-...`）：

- 用户发送 `A`；
- 决策被 HITL 接受（`RESUMED`）；
- **但 cc-connect 日志仍出现模型 turn**：
  `turn complete ... tools=0 response_type silent=true input_tokens=159492 output_tokens=17`。

原因：cc-connect 的 Agent 进程在 Hook 安装前（11:57）已启动并持续复用；
Claude 只在进程启动时加载 settings/hooks，不会热加载。

因此该次测试对“通道隔离”判定为 **FAIL（旧会话）**，不是 Hook 逻辑失败。

### 2.1 新会话复测（`/new`）

14:36:35 用户 `/new`，14:36:48 新会话 s2 启动；同秒 `A` 被 **watch** 接受；
cc-connect 仍执行了模型 turn（22s，input 43275 / output 204）。

日志顺序说明：HITL daemon 的会话文件轮询可能先于 Hook 接受消息；
旧版 Hook 在“无待决候选”时放行，于是双通道仍发生。

已修复：`prompt_router` 增加 `already_handled` 检查——若本聊天最近 300s 内
已有同一文本的已处理决策，Hook 仍 exit 2，阻止 Agent。

因此 s2 测试判定 **FAIL（旧 Hook/竞态）**；修复后需再测。

## 3. 新会话复测（修复后）— PASS

- 14:42:42 `/new` 清理旧会话；
- 14:43:02 用户发送裸 `A`；
- Hook 日志：`invoke has_cc_key=true` → `route block=true outcome=accepted`
  decision `DEC-HITL-ISOLATION-FINAL-20261124-14422901`；
- 决策 `RESUMED`；
- cc-connect 日志：`turn complete ... tools=0 input_tokens=0 output_tokens=0`
  → **没有模型 turn**；
- DingTalk 收到 HITL 回执（hook/Handler 输出）。

结论：新会话 + 修复后的 Hook 实现通道隔离。

普通聊天：14:46:48 一条无 `CC_SESSION_KEY` 的 Claude prompt 被 Hook 放行
（`block=false`），说明无 HITL 上下文时不拦截；**钉钉侧普通聊天真实回复仍标记 NOT_TESTED**。

## 4. 其他真实验收

| 项 | 结果 |
|---|---|
| 显式 DEC-ID A/B/C（历史） | PASS |
| 单决策裸 A（旧会话，Hook 未加载） | 决策 PASS；隔离 FAIL（运行生命周期） |
| 单决策裸 A（s2 新会话，旧 Hook/竞态） | 决策 PASS；隔离 FAIL（已修复 already_handled） |
| 单决策裸 A（修复后新会话） | **PASS**：input/output tokens=0，无模型 turn |
| 多决策裸 B 歧义 | NOT_TESTED（真实） |
| 普通聊天放行 | 自动化 PASS；钉钉侧 NOT_TESTED |
| 重复回复 | NOT_TESTED（本轮真实） |
| `cc_connect_resume` | NOT_TESTED |

## 5. 结论

- 安装/注册：PASS；
- Hook 机制：真实 Claude 进程 PASS；
- 真实 cc-connect 新会话：**PASS**（0 模型 tokens）；
- 旧会话不隔离是运行生命周期事实，需 `/new` 或新进程；
- 钉钉普通聊天真实回复、多决策裸 B 歧义、重复回复、`cc_connect_resume` 仍 NOT_TESTED。
