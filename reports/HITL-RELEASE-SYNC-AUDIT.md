# HITL 发行版同步审计

- 日期：2026-11-21
- 源码：`D:\WorkSpace\task-workflow`（分支 `feat/product-readiness-governance`，HEAD `ae8e578`）
- 发行版：`D:\WorkSpace\lianzhu-skills\zentao-dev-workflow`（分支 `master`，HEAD `a87d92b`，工作区干净）
- 本轮目标：只同步 HITL 回复接收/恢复修复；不发布、不提交、不改源码、不改全局 Skill

---

## 1. 源码基线

未提交（本轮 HITL 修复）：

| 文件 | 类型 |
|---|---|
| `agent-manager/human_decision/cli.py` | 改（daemon 锁释放 Windows 缺陷） |
| `agent-manager/human_decision/decision_manager.py` | 改（创建时自动绑定会话） |
| `agent-manager/human_decision/hitl_config.py` | 改（私聊绑定推断） |
| `agent-manager/human_decision/reply_handler.py` | 改（待决优先/自动绑定/过期保护/未匹配留痕） |
| `agent-manager/human_decision/session_resumer.py` | 改（恢复包根目录） |
| `agent-manager/human_decision/tests/test_reply_binding.py` | 新增 |
| `agent-manager/human_decision/tests/test_daemon_lock.py` | 新增 |

源码测试：`192 passed`（2026-11-21，本轮收尾后）。

---

## 2. 发行版差异结论

- 发行版 `human_decision/` 是**较早同步快照**，缺少源码 HEAD 中的若干 HITL 提交
  （`851e9fe` 决策路由/恢复、`0687e13` HITL DEFAULTS、身份校验加固）。
- 逐文件 diff 方向为**前进**：发行版没有独有的新增逻辑，只有“旧版本内容”。
  因此整文件同步不会覆盖发行版独有改动。
- 发行版已有 `daemon_supervisor.py`、`run_daemon.cmd`、`notifier.py`、`decision_store.py`、
  `reply_parser.py`、`timeout_handler.py`，与源码 HEAD 一致，无需同步。

---

## 3. 同步清单

### A 类：直接属于本轮修复，可同步

| 文件 | 依据 |
|---|---|
| `agent-manager/human_decision/cli.py` | 发行版与源码 HEAD 相同；本轮仅加锁释放修复 |
| `agent-manager/human_decision/session_resumer.py` | 同上；本轮仅修 `_ROOT` 两级 dirname |
| `agent-manager/human_decision/tests/test_reply_binding.py` | 本轮新增回归测试 |
| `agent-manager/human_decision/tests/test_daemon_lock.py` | 本轮新增锁/单消费者测试 |

### B 类：属于 HITL 修复，但依赖其它文件，需一起同步

| 文件 | 依据 / 依赖关系 |
|---|---|
| `agent-manager/human_decision/reply_handler.py` | 本轮核心匹配修复；整文件同步会一并带入源码 HEAD 的身份校验加固（同属 HITL，前进方向） |
| `agent-manager/human_decision/hitl_config.py` | 本轮绑定推断；整文件同步会带入 `notify_transport`/`dingtalk_user_id` DEFAULTS（否则 `dingtalk.local` 配置不生效） |
| `agent-manager/human_decision/decision_manager.py` | 本轮自动绑定；整文件同步带入 `route_decision` 与 `recover(resumer=...)` 调用 |
| `agent-manager/human_decision/recovery_handler.py` | **被 decision_manager 依赖**：新代码调用 `recover(..., resumer=...)`，发行版旧签名不接受该参数 |
| `agent-manager/human_decision/routing.py` | **新文件**：decision_manager 的 L3/P0 路由守卫 `from human_decision.routing import route_decision`；发行版缺失会导致显式等级决策报错 |
| `agent-manager/human_decision/models.py` | `decision_detector` 依赖 `DecisionLevel.normalize/severity`；不随同同步会使 L3 显式等级解析失败 |
| `agent-manager/human_decision/decision_detector.py` | 兼容 L1/L2/L3 与“禁止显式降级”；与 models 成对依赖 |
| `agent-manager/human_decision/tests/conftest.py` | **执行阶段升级为 B**：发行版旧 `sys.path` 顺序会让 `human_decision/cli.py`、`notifier.py` 遮蔽 `agent-manager` 同名模块，完整测试集无法收集；源码 conftest 已修正顺序 |

### C 类：无关或不需要，不同步

| 文件/目录 | 原因 |
|---|---|
| `mcp_server.py` | 与 HEAD 仅 docstring 差异（3 行），无功能变化 |
| `README.md`、`docs/`、`reports/` | 文档；本轮不发布文档 |
| `config/adapters/hitl.example.yaml` | 与源码一致；发行版配置示例已是最新 |
| `config/adapters/hitl.yaml`、`hitl.local.yaml` | 实际/个人配置，禁止带入发行版 |
| `scripts/`、`tests/`（顶层）、`skill/`、`agents/` | 本轮未改动 |
| `agent-manager/logs/`、`.pytest_cache`、`__pycache__`、`*.db` | 运行时/缓存，禁止同步 |

### D 类：暂不处理 / 待验证

| 文件 | 原因 |
|---|---|
| 发行版独有文件 | 审计未发现需要删除/覆盖的独有文件；不删除 |
| `pytest.ini` | 发行版没有该文件；为保持“只同步 HITL 文件”，未新增。完整测试集用显式路径顺序执行（见交付报告） |

---

## 4. 冲突与风险

1. **前进同步范围**：B 类会把源码 HEAD 已提交的 HITL 分级/恢复修复一并带入发行版；
   均为 HITL 范围、发行版无对应独有改动，风险可控，但需在交付报告中披露。
2. **配置键**：发行版仅有 `hitl.example.yaml`，无实际 `hitl.yaml` / `hitl.local.yaml`；
   自动绑定依赖部署方配置 `dingtalk_user_id` 或单一 `deciders`，否则按“不猜测”跳过。
3. **测试基线差异**：发行版顶层测试集与源码不同，可能达不到源码的 `192 passed`；
   以发行版独立执行为准，不伪造。
4. **运行态**：不得把源码 `agent-manager/logs/*.db`、锁文件、`execution/` 带入发行版。
5. **真实 E2E**：新钉钉决策回调、MCP+daemon 并用、重启自启仍未验证，不得宣称端到端通过。

---

## 5. 执行规则

- 使用文件复制，不执行 `git reset/clean/checkout -f`。
- 只复制 A/B 类目标文件；目标目录不存在时创建（`routing.py`）。
- 同步后逐文件 `diff` 校验；在发行版独立运行测试。
