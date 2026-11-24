# 钉钉消息风暴 RCA（2026-11-24）

- 结论：**根因在 cc-connect 的 DingTalk 进度显示模式，不在 Workflow HITL 通知器**。
- 修复：已在 `~/.cc-connect/config.toml` 关闭 thinking/tool 逐事件消息，并 reload 成功。
- 真实消息数量复测：**NOT_TESTED（等待用户发一条普通消息确认）**。

## 1. 完整调用链（实测/源码）

```text
用户钉钉消息
  → cc-connect Stream 收到 message.received
  → cc-connect 把消息作为普通 Agent 输入（产品设计）
  → Claude Code 产生 EventThinking / EventToolUse
  → cc-connect 进度显示：
       - 有 AI Card：更新同一张卡
       - 无 AI Card：DingTalk legacy 模式，每个 thinking/tool 事件 → 一条独立钉钉消息
  → 用户看到几十/上百条“思考中/工具调用”
```

Workflow HITL 的另一条链路只做：

```text
watch ~/.cc-connect/sessions/*.json
  → ReplyHandler 解析 → DecisionStore → SessionResumer
```

它不生成 Thinking，也不向钉钉发送 thinking 消息。

## 2. 证据

### 2.1 cc-connect 日志

反复出现：

```text
WARN msg="streaming card creation failed, falling back to normal messages"
error="dingtalk: card_template_id not configured"
```

伴随每个 turn 的 `msg="message received"` → `processing message` → `turn complete`。
失败样本中一个 turn 持续 52s、输入 158k+ tokens，事件很多。

### 2.2 cc-connect 源码（v1.5.0）

- `core/engine.go`：`CreateStreamingCard` 失败 → `falling back to normal messages`。
- `core/engine.go` EventThinking：
  ```go
  if !cp.AppendEvent(ProgressEntryThinking, ...) {
      if progressStyleForTarget(p, replyCtx) == progressStyleLegacy {
          sendWorkspace(p, replyCtx, thinkingMsg)
      }
  }
  ```
- `core/engine.go` EventToolUse 同样在 legacy 模式下逐条 `sendWorkspace(toolMsg)`。
- DingTalk 平台未实现 `ProgressStyle=card` / `MessageUpdater`，因此 `compactProgressWriter` 不启用，走 legacy。
- `config.DisplayConfig` 提供 `thinking_messages` / `tool_messages` 开关（默认 true）。

### 2.3 Workflow 侧

- `human_decision/notifier.py`：只发送决策通知，无 thinking 文本。
- `human_decision/reply_handler.py`：轮询会话文件，不写钉钉消息。
- 因此“`💭 The user sent ...`”来自 cc-connect 的 Agent 对话，不是 HITL 解析器。

## 3. 责任边界

| 能力 | 归属 |
|---|---|
| 接收钉钉消息 | cc-connect |
| 把消息转成 Agent 输入 | cc-connect |
| Thinking / Tool progress 发送 | cc-connect |
| 是否逐条发/合并发 | cc-connect display 配置 |
| HITL 决策通知 | Workflow（直发/cc-connect 兜底） |
| 决策解析/落库/恢复 | Workflow |
| 阻止 cc-connect 把决策当普通聊天 | **cc-connect 不支持按消息内容区分**；只能换独立机器人/会话，或接受它跑一轮 |

## 4. 修复

`~/.cc-connect/config.toml` 增加（项目级）：

```toml
[projects.display]
thinking_messages = false
tool_messages = false
```

- 由 `config.DisplayConfig` 控制；仅隐藏 thinking/tool 事件，最终回复仍发送。
- `POST /api/v1/reload` 返回：
  ```json
  {"data":{"message":"config reloaded","projects_updated":["personal"]},"ok":true}
  ```
- 未配置 `card_template_id` 时日志仍会提示 card fallback，但不会再逐条发送 thinking/tool。

### 4.1 配置修复说明

检查时发现 `config.toml` 的 `work_dir` 被并发编辑损坏（值为不可解析的路径），
已修复为原工作目录并通过 TOML 校验；
原文件备份在 `~/.cc-connect/config.toml.bak.20261124*`。cc-connect 已重新启动并处于 Running。

## 5. 修复前/后预期

| 场景 | 修复前 | 修复后（预期） |
|---|---|---|
| 普通消息触发多轮思考 | 每个 thinking/tool 事件一条消息 | 不发送 thinking/tool 消息 |
| HITL 裸回复 B | 同样触发一轮 Agent + 多条思考 | 仍可能跑一轮 Agent，但无 thinking/tool 刷屏 |
| 关键决策通知 | 正常发送 | 正常发送（不受 display 影响） |

真实消息条数：用户确认已完成复测，未再反馈风暴；cc-connect 日志对 11:57 / 13:38 / 13:39
每轮只有一次 `turn complete` 与一次 `slow agent send`（最终回复），没有逐条 thinking/tool
发送记录。未采集精确条数，不宣称“从 N 条降到 M 条”。

## 6. 剩余风险

- 配置被 reload 后的运行实例已加载；若 cc-connect 重启，仍从同一 config 读取。
- 如果后续需要“保留进度但不刷屏”，需在钉钉开放平台创建 AI Card 模板并配置 `card_template_id`。
- cc-connect 仍会把 HITL 回复当作普通聊天执行一轮 Agent；彻底隔离需要独立机器人/会话。
