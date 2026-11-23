# HITL 双仓库同步审查与发行版合并准备

- 日期：2026-11-23
- 源码：`D:\WorkSpace\task-workflow`，`feat/product-readiness-governance`，`20164bf`
- 发行版：`D:\WorkSpace\lianzhu-skills`，`sync/hitl-reply-fix-20261121`，`b953a45`
- 本轮未执行 push / merge / Tag / VERSION 修改 / 全局安装

---

## 1. 双仓库 Git 状态

### 1.1 源码仓库

| 项 | 值 |
|---|---|
| 分支 | `feat/product-readiness-governance` |
| HEAD | `20164bf` |
| 父提交 | `ae8e578` |
| 与远程 | 领先 `origin` **3** 个提交，落后 0（未 push） |
| 工作区 | 仅剩会话前已有的未跟踪文档 `docs/Agent 智能研发工作流平台.md`，未纳入提交 |
| 提交文件 | 11 个：5 个 HITL 代码 + 2 个测试 + 4 份报告 |

提交内容无 `.env`、数据库、日志、锁文件、缓存或凭据；新增行未命中 secret 扫描规则。

### 1.2 发行版仓库

| 项 | 值 |
|---|---|
| 分支 | `sync/hitl-reply-fix-20261121`（本地，无 upstream） |
| HEAD | `b953a45` |
| 父提交 | `a87d92b`（= `master` = `origin/master`） |
| 工作区 | 干净 |
| 提交文件 | 12 个，全部位于 `zentao-dev-workflow/agent-manager/human_decision/` |

提交内容无运行时 DB、`.env`、日志、锁、`__pycache__`；未命中 secret 扫描规则。

---

## 2. 文件映射与差异审查

### 2.1 已同步且完全一致（按提交内容 SHA256 比对）

| 源码文件 | 发行版文件 | 结果 |
|---|---|---|
| `human_decision/cli.py` | 同路径 | 一致 |
| `decision_detector.py` | 同路径 | 一致 |
| `decision_manager.py` | 同路径 | 一致 |
| `hitl_config.py` | 同路径 | 一致 |
| `models.py` | 同路径 | 一致 |
| `recovery_handler.py` | 同路径 | 一致 |
| `reply_handler.py` | 同路径 | 一致 |
| `routing.py` | 同路径 | 一致（新增） |
| `session_resumer.py` | 同路径 | 一致 |
| `tests/conftest.py` | 同路径 | 一致 |
| `tests/test_daemon_lock.py` | 同路径 | 一致（新增） |
| `tests/test_reply_binding.py` | 同路径 | 一致（新增） |

说明：`hitl_config.py` / `reply_handler.py` 的工作区为 CRLF（Git autocrlf），索引与提交内容为 LF；`git status` 干净，提交级内容一致，不构成差异。

### 2.2 发行版必要适配差异（不阻塞合并）

| 项 | 说明 |
|---|---|
| `mcp_server.py` | 仅 docstring 差异（发行版仍是旧的 P0/P1/P2 说明）；功能代码一致，`build_server()` 通过 |
| `skill/SKILL.md` | 发行版 Skill 落后于源码的多任务/预检更新（非本轮 HITL 范围）；HITL 的 `mcp__human-decision__request_human_decision` 指令仍完整 |
| `.mcp.json` | 发行版缺失；HITL README 提到“项目级 .mcp.json 已注册”与实际不符（见风险） |
| `requirements.txt` | 发行版缺失；源码为 `PyYAML>=6.0`（见风险） |
| `pytest.ini` | 发行版缺失；完整测试集需显式路径顺序（见测试） |
| `VERSION` / Tag | 发行版无 `VERSION`，无 Tag；本轮不修改 |

### 2.3 行为审查结论

| 审查点 | 结论 | 代码证据 |
|---|---|---|
| 回复 ↔ decision_id 绑定 | 正确：显式 DEC-ID 优先；同聊天已绑定待决唯一命中；未绑定待决按最近通知自动绑定 | `reply_handler._resolve_decision` / `_bind_chat`；`decision_manager.create_decision` 自动绑定 |
| 身份校验与任务隔离 | 未放宽：决策人白名单 fail-closed；按 chat_session_key/任务隔离；空 user_id 不放行 | `reply_handler._check_identity`；`HitlConfig.is_authorized` |
| 重复回复 | 唯一约束 `(decision_id, msg_id)` + 原子状态转移，重复不重复执行 | `decision_store.record_reply` / `transition` |
| 过期回复 | 超时后仍可回复；超过 12h 的未绑定决策不自动认领，需显式 DEC-ID | `ReplyHandler._AUTO_BIND_MAX_AGE_SECONDS` / `_pick_unbound` |
| 非法回复 | 解析失败/无效选项 → 拒绝并留痕；未匹配 → `reply_unmatched` 事件 | `reply_parser.parse_reply`；`reply_handler.handle` |
| `routing.py` | L1/L2/P2→auto，L3/P0→hitl，P1→hitl；实测输出正确 | `routing.route_decision` |
| Session 恢复优先级 | live_continue → cc_connect_resume → checkpoint_rebuild；恢复包根目录已修正 | `session_resumer.resume`；`_ROOT` |
| Runner 重启恢复 | `recovery_handler.recover(resumer=...)` 重试 DECISION_RECEIVED/RESUMING/RESUME_FAILED | `recovery_handler.py`；`test_recovery_after_restart` |
| MCP / Skill 调用 | 发行版 `mcp_server.build_server()` 通过；Skill 中 HITL 工具名完整 | 实测 + `skill/SKILL.md` |
| 配置/安装 | `hitl.example.yaml`、`hitl.local.example.yaml` 与源码一致；`install.sh` 语法通过 | diff + `bash -n` |

未发现“回复错误关联其他任务”“已决决策抢占待决回复”“重复执行”的行为回归。

---

## 3. 本轮实际测试结果

### 3.1 源码仓库

```text
python -I -m pytest
→ 192 passed, 1 warning

python -I -m pytest \
  agent-manager/human_decision/tests/test_reply_binding.py \
  agent-manager/human_decision/tests/test_daemon_lock.py \
  agent-manager/human_decision/tests/test_manager.py \
  agent-manager/human_decision/tests/test_resumer.py -v
→ 28 passed
```

覆盖：自动绑定、跨任务不串、已决不抢待决、提醒不抢回复、歧义要求 DEC-ID、12h 过期、迟到回复、daemon 单消费者/锁恢复、重启恢复、checkpoint 恢复。

### 3.2 发行版仓库（独立执行）

```text
cd D:\WorkSpace\lianzhu-skills\zentao-dev-workflow
python -I -m pytest agent-manager/human_decision/tests -q
→ 71 passed

python -I -m pytest \
  agent-manager/human_decision/tests/test_reply_binding.py \
  agent-manager/human_decision/tests/test_daemon_lock.py \
  agent-manager/human_decision/tests/test_manager.py \
  agent-manager/human_decision/tests/test_resumer.py -q
→ 28 passed

python -I -m pytest tests agent-manager/tests agent-manager/human_decision/tests -q
→ 261 passed, 1 warning
```

独立运行验证：

```text
human_decision.reply_handler.__file__ =
  D:\WorkSpace\lianzhu-skills\zentao-dev-workflow\agent-manager\human_decision\reply_handler.py
_AUTO_BIND_MAX_AGE_SECONDS = 43200
py_compile：全部同步文件通过
routing：L1/L2/P2→auto，L3/P0→hitl，P1→hitl
```

注意：发行版没有 `pytest.ini`，直接 `python -I -m pytest` 会因收集顺序导致
`human_decision/cli.py`、`notifier.py` 遮蔽 agent-manager 同名模块；完整集必须使用上述显式路径顺序。

---

## 4. 风险清单

| 严重度 | 风险 | 影响 | 建议 |
|---|---|---|---|
| MEDIUM | 真实钉钉新决策 E2E 未验证 | 修复逻辑有单测与真实消息重放，但没有“修复后新回调”证据 | 合并后安排一次真实 L3 决策验证 |
| MEDIUM | 发行版缺 `.mcp.json`，HITL README 说“已注册” | 项目级 MCP 不会自动可用；用户需执行 `claude mcp add` | 合并后单独补 `.mcp.json` 或修正 README |
| MEDIUM | 发行版缺 `requirements.txt`，未文档化 PyYAML/MCP 依赖 | 新环境可能缺依赖 | 补依赖清单/安装说明（独立变更） |
| LOW | 发行版无 `pytest.ini` | 默认测试命令收集失败 | 补 `pytest.ini` 或文档化显式命令 |
| LOW | `skill/SKILL.md` 落后源码 | 不影响 HITL，但发行版 Skill 缺多任务/预检说明 | 另开同步任务 |
| LOW | 发行版无 VERSION/Tag | 版本追溯弱 | 合并后决定版本策略 |
| LOW | `mcp_server.py` docstring 旧 | 仅帮助文本 | 可随下次同步修正 |

无 HIGH/CRITICAL 风险；无冲突；未发现凭据或开发机绝对路径。

---

## 5. 合并准备检查

| 检查项 | 结果 |
|---|---|
| `master` 是否为同步分支祖先 | 是（`merge-base --is-ancestor` rc=0） |
| master 与分支差异 | `0` 个 master 独有提交，`1` 个分支提交 |
| 是否可 fast-forward | 是 |
| 冲突预演 | `git merge-tree --write-tree master sync/...` 返回 tree `aa79b05...`，rc=0，无冲突 |
| 合并文件范围 | 仅 12 个 HITL 文件；无 reports、`.env`、DB、日志、缓存 |
| master 工作区 | 干净；HEAD 与 `origin/master` 一致 |
| 覆盖 master 改动风险 | 无：master 在分支点后无新提交 |

### 建议合并方案（本轮不执行）

```bash
cd D:\WorkSpace\lianzhu-skills
# 合并前确认 master 无新提交（需要联网时）
# git fetch origin && git status
git switch master
git merge --ff-only sync/hitl-reply-fix-20261121
git log --oneline -3
git status
```

不使用 `--no-ff`/`squash`：当前为干净的 fast-forward，保留单提交历史。

---

## 6. 是否建议合并

**建议合并到 `master`：是。**

理由：

- 12 个映射文件提交级完全一致；
- 发行版独立测试通过（HITL 71、完整 261）；
- fast-forward 无冲突，不覆盖 master 已有改动；
- 合并范围严格限定在 HITL，无开发文件/运行时数据。

不建议在本次合并中顺带处理：`.mcp.json`、`requirements.txt`、`pytest.ini`、Skill 多任务文档、VERSION/Tag——这些是独立的发布工程事项。

---

## 7. 合并前置条件

1. 确认 `master` 仍指向 `a87d92b`（若 origin 有更新，先 fetch 并重新评估）。
2. 两个仓库工作区保持干净（当前满足；源码仅剩无关未跟踪文档）。
3. 合并后立即在 master 上复跑发行版测试：
   `python -I -m pytest agent-manager/human_decision/tests -q` → 71 passed；
   `python -I -m pytest tests agent-manager/tests agent-manager/human_decision/tests -q` → 261 passed。
4. 合并后不立即 push；等待用户授权。
5. 真实钉钉 E2E 未完成前，对外表述为“修复已合并、E2E 待验证”。

---

## 8. 后续建议

| 动作 | 建议 |
|---|---|
| push | 源码 `feat/product-readiness-governance` 领先 origin 3 个提交；发行版合并后由用户决定推送时机 |
| Tag | 发行版无 Tag；建议在真实 E2E 通过后再打 HITL 修复 Tag |
| VERSION | 源码为 `0.9.0`，发行版无 `VERSION`；建议统一版本策略后再发版 |
| 全局安装 | 本轮不做；合并验证后由用户执行安装/同步 |
| 真实 E2E | 新建一条真实 L3 决策，验证钉钉回复 → 自动绑定 → 接受 → 恢复；另测 MCP 与 daemon 并存、重启自启 |
| 发布工程 | 单独补 `.mcp.json`、`requirements.txt`、`pytest.ini`，修正 HITL README 的“已注册”表述 |

---

## 9. 本轮未做

- 未 push、未 merge、未修改 master；
- 未打 Tag、未修改 VERSION；
- 未安装全局 Skill；
- 未清理任何用户文件；
- 未创建真实决策或派发 Agent。
