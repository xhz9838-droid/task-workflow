# HITL 可靠性回归（2026-11-24）

## 1. 自动化结果

| 范围 | 结果 |
|---|---|
| 源码全量 | **222 passed** |
| 发行版全量 | **293 passed** |
| 发行版 HITL | **101 passed** |

新增/更新测试：

- `test_reply_formats.py`：A/B/C、DEC-ID、标点、自然语言、防误判；
- `test_reply_binding.py`：
  - 样本 A（3413 RESUMED + 3657 过期 + 3442 新）首次 B 命中 3442；
  - 多个新鲜未绑定 → 提示候选 DEC-ID，不猜测；
  - 显式 DEC-ID 跨聊天拒绝；
  - 显式 DEC-ID + C + 自定义意见；
  - 重复/迟到/超时/daemon 锁。
- `test_process_lock.py` / `test_daemon_lock.py` / `test_install_flags.py` 保持通过。

## 2. 能力回归

| 能力 | 状态 | 说明 |
|---|---|---|
| live_continue | PASS | 2026-11-23 真实 Session |
| checkpoint_rebuild | PASS | 恢复包 + 新 Session |
| cc_connect_resume | NOT_TESTED | 无隔离 cc-connect 会话 |
| 身份白名单 | PASS | 测试覆盖；跨聊天显式 ID 拒绝 |
| decision_id 绑定 | PASS | 显式优先 + 唯一候选自动绑定 |
| Chat/Session 绑定 | PASS | 绑定其他聊天拒绝 |
| 重复回复拒绝 | PASS | 唯一约束 + 原子状态 |
| SQLite 持久化 | PASS | 决策/回复/事件 |
| Daemon/Supervisor 锁 | PASS | PID+启动时间+token；13 项锁测试 |
| start/stop/status/restart/recover | PASS（Windows） | lifecycle CLI 实测；macOS 未测 |
| install.sh 参数边界 | PASS | `--check` 只读、`--init-config` 不安装 |
| MCP 注册 | 未在本轮修改 | 现有指向源码 |
| 原有钉钉通知 | PASS | 决策通知仍发送 |
| 消息风暴治理 | 配置已生效 | display 关闭 thinking/tool；真实条数未复测 |

## 3. 运行状态

- cc-connect：Running（PID 43972），DingTalk Stream 已连接；
- 源码 daemon/supervisor：Running；
- 发行版 daemon：Stopped；
- `.home`：源码运行时根；
- MCP：指向源码（本轮未改）。

## 4. 未验证项

1. 真实钉钉 D03/D04/D05（自定义意见/自然语言）；
2. 真实多决策并发（三条测试决策等待回复）；
3. 修复后真实消息条数（需要用户在钉钉发普通消息）；
4. `cc_connect_resume`；
5. 多用户真实账号；
6. macOS lifecycle；
7. 干净 Windows 安装。

## 5. 遗留风险

- cc-connect 仍会把 HITL 回复当作普通聊天执行一轮 Agent；display 只抑制 thinking/tool 刷屏，
  不能阻止该轮 Agent 运行。
- 若配置了 AI Card，可进一步合并进度；未配置时日志仍提示 card fallback。
- 并发消费者（daemon + MCP）依赖 `(decision_id,msg_id)` 唯一约束；真实压力未测。
