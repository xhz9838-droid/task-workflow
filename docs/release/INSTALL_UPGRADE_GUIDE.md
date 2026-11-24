# 安装 / 升级 / 迁移指南（2026-11-24）

## 0. 默认用户目录（发行版推荐）

```bash
# 安装到 ~/.workflow（macOS $HOME/.workflow）
bash scripts/install.sh --default-dir
bash scripts/install.sh --default-dir --with-mcp

# 自定义根（支持 D 盘、含空格路径）
bash scripts/install.sh --default-dir --dir "D:/My Workflows"
```

结构：

```text
.workflow/
├── runtime/        # 程序
├── config/         # 配置 + .env
├── data/execution/ # 执行状态/checkpoint
├── logs/           # SQLite/HITL 日志
├── backups/
└── install.json
```

程序目录中的 `config`、`execution`、`agent-manager/logs` 链接到上述用户目录；
默认目录安装后再用 `--default-dir` 即为原目录升级。同一用户目录禁止并发安装（锁冲突 exit 3）。

## 1. 首次安装（run-in-place）

```bash
cd <WORKFLOW_HOME>
python -m pip install -r requirements.txt
bash scripts/install.sh --check
bash scripts/install.sh
bash scripts/install.sh --with-mcp   # 可选：注册 HITL MCP
```

安装内容：Skill、7 个 Agent、HITL Hook、`.home`；Settings 自动备份，其他 Hooks 保留。

## 2. 原目录升级

```bash
cd <WORKFLOW_HOME>
git pull   # 或替换为新版本文件
python -m pip install -r requirements.txt
bash scripts/install.sh --upgrade
```

默认 `install.sh` 与 `--upgrade` 等价；重复执行幂等。

## 3. 跨目录迁移

旧目录 `v1`，新目录 `v2`：

```bash
cd <v2>
bash scripts/install.sh --migrate
```

迁移会：

- 识别唯一旧运行时根（`.home` / 用户 JSON / Hook / MCP）；
- 备份用户级配置；
- 复制 `config/`、`.env`、`execution/`、SQLite（只补新目录缺失项）；
- 更新用户 JSON、`.home`、Hook、MCP；
- 健康检查；失败恢复备份，旧目录保留。

多个旧根会报 `MULTIPLE_OLD_ROOTS` 并停止，不猜测。

## 4. 检查

```bash
bash scripts/install.sh --check
bash scripts/install.sh --check --json
```

输出 Runtime / User Config / Hook / MCP / Skill / Agents / Dependencies / Runtime Data 状态；
异常时给 Fix。

## 5. 初始化配置

```bash
bash scripts/install.sh --init-config
```

只生成 `config/adapters/hitl.local.yaml`（不覆盖），不安装、不改 settings。

## 6. 卸载

```bash
bash scripts/install.sh --uninstall
```

只移除本工作流 Hook、Skill、Agents、`.home`；保留其他 Skill/Agent/Hook/MCP、`config/`、`execution/`、`.env`、SQLite。

## 7. 升级后必须做

- **新开 Claude Code 会话**；
- cc-connect 用户在钉钉发送 `/new`；
- 旧进程不会热加载新 Hook/settings。

## 8. 数据保护

| 数据 | 处理 |
|---|---|
| `config/` | 安装不动；迁移只补缺失文件 |
| `.env` | 不动；迁移仅新目录缺失时复制 |
| `execution/` | 不动；迁移仅新目录缺失时复制 |
| SQLite | 不动；迁移用 SQLite backup API 生成一致副本 |
| 用户 JSON / settings / MCP | 迁移前备份，失败恢复 |
| cc-connect 配置 | 不读写、不重启 |

## 9. Windows / macOS

- 命令在 Git Bash（Windows）或 bash/zsh（macOS）执行。
- Windows 路径推荐使用盘符路径；`native_root` 会转换为 `C:/...` 形式。
- macOS 需确保 `python3` 可用；可设 `PYTHON_BIN=python3`。
- 路径含空格时，脚本对 Hook/MCP 命令加引号；仍建议避免特殊字符。

## 10. 回滚

- 用户配置备份：`settings.json.bak.*`、`.home.bak.install.*`、`zentao-dev-workflow.json.bak.install.*`、`.claude.json.bak.install.*`。
- 迁移失败：自动恢复上述文件；旧目录保留。
- 旧版本目录不会被删除，可手动切回（并重新运行对应版本安装）。
