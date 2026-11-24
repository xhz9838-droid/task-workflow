# HITL 回复通道隔离 RCA（2026-11-24）

## 1. 双通道根因

```text
钉钉消息
  ├─→ cc-connect：当作普通聊天 → 启动 Claude Agent turn
  └─→ Workflow HITL watch：轮询 ~/.cc-connect/sessions/*.json → 处理决策
```

HITL 是**旁路消费者**，不是 cc-connect 的前置路由；因此同一消息会被两边同时处理。

cc-connect v1.5.0 现状（源码核实）：

- `core/hooks.go`：`message.received` hook 是 **fire-and-forget**，command/http 返回值/退出码不会阻止 Agent。
- `core/engine.go`：hook 在 banned_words 检查之前发出，但 hook 无权修改/丢弃消息。
- `banned_words` 是静态子串列表，可在 Agent 前丢弃消息；无法按“当前是否有待决策”条件判断，
  也不能在不误伤普通聊天的情况下覆盖 `A/B/C`。
- 未发现 plugin / interceptor / pre-message middleware 接口。

结论：**不修改 cc-connect 源码，无法让它按 HITL 上下文跳过 Agent**。

## 2. 方案比较

| 方案 | 是否修改第三方 | 效果 | 结论 |
|---|---|---|---|
| A. Claude Code `UserPromptSubmit` hook 路由 | 否 | 在模型 turn 前拦截；HITL 处理→exit 2 阻止 Agent；普通聊天放行 | **已实现（未激活）** |
| B. cc-connect 源码增加 blocking hook | 是 | 可在 cc-connect 内彻底不启动 Agent | 需第三方补丁/升级，未做 |
| C. 独立钉钉机器人 + Workflow 入站服务 | 否 | 彻底隔离 | 新基础设施，未做 |
| D. `banned_words` 静态过滤 | 否 | 只能过滤固定文本，无法覆盖裸 A/B/C | 不可行 |

## 3. 已实现方案 A：`prompt_router.py`

`agent-manager/human_decision/prompt_router.py`：

- 读取 Claude Code hook JSON（`prompt`、`session_id`）。
- 从 env 读取 cc-connect 注入的 `CC_SESSION_KEY`（源码 `core/engine.go` 确认注入）。
- 只取**本聊天已绑定**的 `WAITING_REPLY` 决策作为候选。
- 判断消息是否像 HITL：
  - 显式 DEC-ID；
  - 单字母/STOP；
  - 合法选项/自定义意见/自然语言选择。
- 是 HITL → `DecisionManager.apply_reply` → `exit 2` 阻止普通 Agent；
- 普通聊天（如“你好”）→ `exit 0` 放行。
- 歧义/非法/无权限 → 同样 exit 2，返回澄清，不退化普通聊天。

### 3.1 激活方式（需用户授权，本轮未安装）

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python -I <WORKFLOW_HOME>/agent-manager/human_decision/prompt_router.py"
          }
        ]
      }
    ]
  }
}
```

配置到用户级或 cc-connect 工作目录级别的 Claude settings 后，新会话生效。

## 4. 真实 Claude hook 验证

使用临时 `--settings`（不改用户配置）和 `CC_SESSION_KEY`：

```bash
CC_SESSION_KEY='dingtalk:d:...:<uid>' \
claude -p "A" --settings <temp-settings.json>
```

输出：

```text
UserPromptSubmit operation blocked by hook:
[...prompt_router.py]: 已收到决策（DEC-HITL-HOOK-TEST-...）：A
```

- 决策状态变为 `RESUMED`；
- 没有模型回复/思考输出；
- 证明“HITL 处理并阻止模型 turn”在真实 Claude Code 进程内可行。

限制：

- cc-connect 仍会启动 Claude 进程，只是 prompt 被 hook 拦截，**没有模型 turn**；
  如果要求“进程也不启动”，必须走方案 B（cc-connect 补丁）。
- 未在真实 cc-connect 用户设置中激活，因此 cc-connect 端到端通道隔离标记 **NOT_TESTED**。
- 群聊无法从会话键取发送人 userId；当前仅私聊可靠。
