# HITL 源码 → 发行版受控同步报告

- 日期：2026-11-21
- 源码：`D:\WorkSpace\task-workflow`
- 发行版：`D:\WorkSpace\lianzhu-skills\zentao-dev-workflow`
- 结论：**SYNCED_WITH_LIMITATIONS**

---

## 1. 源码基线

| 项 | 值 |
|---|---|
| 分支 | `feat/product-readiness-governance` |
| HEAD | `ae8e578` |
| 未提交 HITL 代码 | 5 改 + 2 新增测试（见审计报告） |
| 源码测试 | `192 passed` |

本轮未修改源码代码；仅新增审计/交付报告到源码 `reports/`（任务要求）。

---

## 2. 发行版同步前状态

| 项 | 值 |
|---|---|
| 仓库 | `lianzhu-skills`（分支 `master`，HEAD `a87d92b`） |
| 工作区 | 干净 |
| HITL 基线 | 早于源码 HEAD 多个 HITL 提交（路由/恢复/DEFAULTS/身份校验） |
| HITL 测试基线 | `agent-manager/human_decision/tests`：**56 passed** |

---

## 3. 实际同步文件（12）

### A 类（本轮直接修复）

| 文件 |
|---|
| `agent-manager/human_decision/cli.py` |
| `agent-manager/human_decision/session_resumer.py` |
| `agent-manager/human_decision/tests/test_reply_binding.py`（新增） |
| `agent-manager/human_decision/tests/test_daemon_lock.py`（新增） |

### B 类（本轮修复 + 必要依赖）

| 文件 | 依赖说明 |
|---|---|
| `agent-manager/human_decision/reply_handler.py` | 本轮核心匹配修复 + 既有身份校验加固 |
| `agent-manager/human_decision/hitl_config.py` | 绑定推断 + `notify_transport`/`dingtalk_user_id` DEFAULTS |
| `agent-manager/human_decision/decision_manager.py` | 自动绑定 + L3 路由/恢复调用 |
| `agent-manager/human_decision/recovery_handler.py` | 被 `decision_manager.recover(resumer=...)` 依赖 |
| `agent-manager/human_decision/routing.py`（新增） | `decision_manager` L3/P0 路由守卫依赖 |
| `agent-manager/human_decision/models.py` | `DecisionLevel.normalize/severity`，供 detector 使用 |
| `agent-manager/human_decision/decision_detector.py` | 兼容 L1/L2/L3、禁止显式降级 |
| `agent-manager/human_decision/tests/conftest.py` | 修正 `sys.path` 顺序，避免 `human_decision/cli.py`、`notifier.py` 遮蔽 agent-manager 同名模块 |

同步方式：文件复制；未执行 `git reset/clean/checkout -f`。

---

## 4. 跳过文件及原因

| 文件/目录 | 原因 |
|---|---|
| `mcp_server.py` | 与源码 HEAD 仅 3 行 docstring 差异，无功能变化 |
| `README.md`、`docs/`、`reports/` | 文档；本轮不发布文档 |
| `config/adapters/*.example.yaml` | 与源码一致，无需同步 |
| `config/adapters/hitl.yaml`、`hitl.local.yaml`、`.env` | 实际/个人配置，禁止带入发行版 |
| `scripts/`、顶层 `tests/`、`skill/`、`agents/` | 本轮未改动 |
| `agent-manager/logs/`、`.pytest_cache`、`__pycache__` | 运行时/缓存；未复制 |

---

## 5. 冲突与风险

1. **前进同步**：B 类文件把源码 HEAD 已提交的 HITL 分级/恢复/DEFAULTS/身份校验一并带入发行版。
   逐文件 diff 均为“发行版较旧”，未发现发行版独有逻辑，未覆盖任何独有改动。
2. **测试基础设施**：发行版没有 `pytest.ini`；直接 `python -I -m pytest` 会因收集顺序导致
   `human_decision/cli.py`、`notifier.py` 遮蔽 agent-manager 同名模块。本次用显式路径顺序执行，
   未新增 `pytest.ini`（不在本轮同步范围）。
3. **配置**：发行版只有 `hitl.example.yaml`，没有实际 `hitl.yaml`/`hitl.local.yaml`；
   自动绑定需要部署方配置 `dingtalk_user_id` 或单一 `deciders`，否则按“不猜测”跳过。
4. **运行时文件**：发行版已有 `agent-manager/logs/agent_manager.db`（2026-11-20，gitignored），
   为发行版自身历史运行产物，**非本次从源码复制**；未删除。
5. **真实 E2E**：新钉钉决策回调、MCP+daemon 并存消费、Windows 重启自启仍未验证。

---

## 6. 源码与发行版一致性

12 个同步文件逐一 SHA256 对比：**全部 OK / 无差异**。

未发现指向开发机的绝对路径：

```text
rg "D:\\WorkSpace\\task-workflow|D:/WorkSpace/task-workflow" release/
→ none
```

仅存在注释/测试临时目录名 `task-workflow`，不是开发机路径依赖。

---

## 7. 发行版独立测试结果

| 范围 | 命令 | 结果 |
|---|---|---|
| HITL（含新增） | `python -I -m pytest agent-manager/human_decision/tests -q` | **71 passed**（56 基线 + 15 新增） |
| 完整测试集 | `python -I -m pytest tests agent-manager/tests agent-manager/human_decision/tests -q` | **261 passed** |
| 模块导入 | 独立进程导入 `cli/decision_manager/hitl_config/reply_handler/session_resumer/routing/recovery_handler/models/decision_detector`；`mcp_server.build_server()` | OK；`_AUTO_BIND_MAX_AGE_SECONDS=43200` |

说明：发行版完整测试集为 261 项（比源码 192 多，因其保留了更多历史顶层测试）；这是发行版独立执行结果，不应直接等同源码测试集。

---

## 8. MCP / daemon / supervisor 检查

| 项 | 结果 |
|---|---|
| 本机 MCP 注册 `~/.claude.json` | 仍指向源码 `D:\WorkSpace\task-workflow\...\mcp_server.py`，**未修改** |
| 发行版 Skill 入口 | `skill/SKILL.md` 存在，明确引用 `mcp__human-decision__request_human_decision` |
| 发行版 `.mcp.json` | 无（发行版通过安装/文档配置；本轮不安装） |
| daemon/supervisor 文件 | 发行版 `daemon_supervisor.py`、`run_daemon.cmd` 与源码 HEAD 一致；本轮未改 |
| 当前运行 daemon/supervisor | 仍使用源码路径，未受发行版同步影响 |
| 全局 Skill 安装目录 | 未修改 |

---

## 9. 尚未完成的真实 E2E

- 修复后**全新** L3 决策：钉钉通知 → 用户回复 → 自动绑定 → 接受 → 恢复；
- 新 MCP 会话与 daemon 并存的真实消息消费；
- Windows 注销/重启后 supervisor 自启与 daemon 接管。

以上均未执行，不宣称端到端通过。

---

## 10. 最终结论

**SYNCED_WITH_LIMITATIONS**

- HITL 修复及必要依赖已受控同步，发行版文件与源码逐一一致；
- 发行版独立测试通过：HITL 71 passed、完整 261 passed；
- 未同步任何运行时/个人配置/凭据；
- 存在限制：前进同步带入了既有 HITL 修复、发行版无 `pytest.ini`（需显式路径顺序）、真实钉钉 E2E 未验证。

本轮未提交 Git、未升级 VERSION、未打 Tag、未发布安装包、未修改全局 Skill。
