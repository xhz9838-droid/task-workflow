# 安装可靠性最终验收（2026-11-24）

## 结论

**默认用户目录已真正落地，发行版可脱离源码独立安装运行。**

- Windows 隔离环境：**PASS**
- macOS：**NOT_TESTED**（无实机，仅代码兼容性检查）
- 生产用户安装路径/迁移：**未触碰**（保护边界）

## 1. 默认目录实现

新增发行版入口：

```bash
bash scripts/install.sh --default-dir                 # ~/.workflow
bash scripts/install.sh --default-dir --dir "D:/My Workflows"  # 自定义根
bash scripts/install.sh --default-dir --with-mcp
```

实际结构（Windows `%USERPROFILE%\.workflow`，macOS `$HOME/.workflow`）：

```text
.workflow/
├── runtime/        # 程序副本（scripts/agent-manager/skill/agents）
├── config/         # workflow/projects/users/adapters + .env
├── data/
│   └── execution/  # execution/{project}/{task}、checkpoint
├── logs/           # agent_manager.db、HITL/daemon 日志
├── backups/        # 保留目录（用户配置备份仍就近保留）
└── install.json    # 安装清单
```

分离方式：

| 运行路径 | 物理位置 | 方式 |
|---|---|---|
| `runtime/config` | `.workflow/config` | Windows Junction / Unix symlink |
| `runtime/execution` | `.workflow/data/execution` | 同上 |
| `runtime/agent-manager/logs` | `.workflow/logs` | 同上 |
| `config/.env` | `.workflow/config/.env` | 真实文件；代码优先读取 |
| SQLite | `.workflow/logs/agent_manager.db` | 经 logs 链接 |
| Checkpoint | `.workflow/data/execution/...` | 经 execution 链接 |

`install.json` 实际内容（节选）：

```json
{
  "schema": 1,
  "installed_at": "2026-11-24T16:02:36+08:00",
  "source": "D:\\WorkSpace\\lianzhu-skills\\zentao-dev-workflow",
  "home": "D:\\WorkSpace\\tmp-wf-final\\user\\.workflow",
  "runtime": "D:\\WorkSpace\\tmp-wf-final\\user\\.workflow\\runtime",
  "config": "D:\\WorkSpace\\tmp-wf-final\\user\\.workflow\\config",
  "data": "D:\\WorkSpace\\tmp-wf-final\\user\\.workflow\\data",
  "logs": "D:\\WorkSpace\\tmp-wf-final\\user\\.workflow\\logs",
  "backups": "D:\\WorkSpace\\tmp-wf-final\\user\\.workflow\\backups",
  "mcp": true
}
```

`_home.py` 未改优先级；它读取 `.home` 指向 `runtime`，并通过 `runtime/config` 链接通过原有校验。旧 run-in-place 目录继续可用。

## 2. 发行版独立运行

隔离 HOME、临时 user、从发行版复制到 `.workflow/runtime`，未设置 `WORKFLOW_HOME`：

| 项 | 实测 |
|---|---|
| `_home.py` 解析 | `.workflow/runtime`，来源 `安装记录` |
| `--check` | `INSTALLED (READY)` |
| Hook 命令 | `python -I "<home>/runtime/agent-manager/.../prompt_router.py"` |
| MCP | `human-decision` 指向 `<home>/runtime/.../mcp_server.py` |
| Skill/Agent | 从 `runtime/skill`、`runtime/agents` 安装 |
| 源码引用 | `grep task-workflow` 在安装根/用户配置中 **0 命中** |
| 其他 Hook/MCP | 保留 |

## 3. Windows 路径矩阵

| 场景 | 结果 | 证据 |
|---|---|---|
| 默认 `%USERPROFILE%\.workflow` | PASS | 隔离 HOME 安装，`--check READY` |
| D 盘自定义目录 | PASS | `D:\WorkSpace\tmp-wf-acceptance\space base` |
| 路径含空格 | PASS | 上述路径含 `space base`，Hook/MCP 引号正确 |
| 非系统盘 | PASS | 使用 D 盘（系统盘为 C） |
| 旧路径迁移到默认目录 | PASS | 旧 `.home`/JSON/Hook/MCP/SQLite 全部更新 |

Python 子进程、Hook、MCP 均实测指向新 `runtime`；未出现旧路径残留。

## 4. 升级与迁移

- 默认目录重复执行 `--default-dir`：幂等，Hook 不重复，代码副本更新；并发安装被锁拒绝（exit 3）。
- 旧根 → 默认目录：
  - 旧 `config/projects`、`.env`、`execution`、SQLite、日志复制到新目录；
  - `.home`、用户 JSON、Hook、MCP 全部指向新 `runtime`；
  - 其他 Hook/MCP 保留；旧目录保留。
- 多个旧根：`MULTIPLE_OLD_ROOTS`，拒绝修改。
- 迁移失败：`--migrate` 恢复 `.home`/用户 JSON/settings；测试注入损坏 `.claude.json` 后 PASS。
- 旧 `.env` 实际落到 `config/.env`；同时为兼容生成 `runtime/.env` 硬链接（若安装时已存在）。

## 5. HITL 回归（隔离用户）

默认安装后，创建单条等待决策 `DEC-FINAL-1`（选项 A/B/C），通过 `UserPromptSubmit` Hook 输入裸 `A`：

```text
ROUTER_RC=2
DEC DecisionStatus.RESUMED A A
```

- 决策被识别并阻止进入普通 Agent（exit 2）；无模型 turn，不产生 thinking 消息风暴。
- `logs/hitl-prompt-router.log` 仅 1 条 `invoke` + 1 条 `route(accepted)`。
- 检查点实际写入：
  `runtime/execution/P/T1/human-decision/...` → 物理
  `data/execution/P/T1/human-decision/...`。
- MCP 服务可构建，工具：`request_human_decision`、`get_human_decision`、`list_human_decisions`。
- 原有其他 MCP 服务未修改。

## 6. macOS 待实机验证

代码层仅使用 bash/Python/`os.symlink`，未发现 Windows 专属必需路径；但以下必须实机确认：

1. `~/.workflow` 创建与 `runtime/{config,execution}` 软链；
2. `runtime/agent-manager/logs` 软链下 SQLite 可读写；
3. `config/.env` 读取；
4. Hook 命令引号/空格路径；
5. MCP 启动与 `--check READY`；
6. 旧目录迁移与回滚。

未实机前不得标记 macOS PASS。

## 7. 测试数量

| 范围 | 结果 |
|---|---|
| 源码全量 | **231 passed** |
| 发行版全量 | **314 passed** |
| 发行版 HITL | **110 passed** |
| 安装/迁移专项 | **14 passed**（`test_install_flags.py` 9 + `test_install_default.py` 5） |

## 8. Git 状态

- 源码 `main`：代码提交 `8157a74`；工作区仅剩 `config/projects/jeebootx.yaml` 他人未提交修改（未触碰）。
- 发行版 `master`：代码提交 `06bf7ad`；`origin/master` 为 `f77e5c3`，本地领先 4 个提交（代码/锁修复 + 文档；SHA 见 git log）；工作区干净。
- 未 push、未 Tag、未改 VERSION、未全局发布。
- 本文件随后的文档提交仅补充 SHA/验收结论，不改运行时代码。

## 9. 剩余风险

1. **macOS 未实机**；软链/权限/Hook 执行需验证。
2. 默认目录依赖目录链接；若用户环境禁止 symlink 且 `mklink /J` 不可用，安装会明确失败（不会静默复制造成数据分裂）。
3. 并发安装同一用户目录会争用文件锁（验收时并行执行曾触发超时）；已加 `.zentao-dev-workflow.install.lock`，第二个进程直接 exit 3；串行默认安装 3 次均 1–2s 通过。
4. `backups/` 当前只创建目录；用户配置备份仍就近保存（`settings.json.bak.*` 等），未集中迁移。
5. `install.json` 记录发行版来源路径（安装溯源用），不参与运行时解析；如交付要求零开发路径，可后续改为版本号/包名。
