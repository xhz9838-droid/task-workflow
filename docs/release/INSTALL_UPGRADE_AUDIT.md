# 安装、升级与迁移审计（2026-11-24）

## 1. 当前安装架构

- **run-in-place**：Skill 只安装文档到 `~/.claude/skills/`，运行时代码/配置/数据在运行时根。
- 运行时根通过 `_home.py` 解析：`WORKFLOW_HOME` → `~/.claude/zentao-dev-workflow.json` → `.home` → 脚本仓库 → 向上探测。
- 安装入口：`scripts/install.sh`（Skill/Agent/Hook/`.home`），`scripts/hitl_hook.py`（Hook 合并），MCP 注册。
- 发行版与源码是两个 Git 仓库；发行版 `install.sh` 为分发入口。

## 2. 配置优先级（实际问题）

| 配置 | 优先级 | 说明 |
|---|---|---|
| `WORKFLOW_HOME` | 1 | 显式环境变量，最高 |
| `~/.claude/zentao-dev-workflow.json` | 2 | 早期源码安装会写 `workflow_home` |
| `~/.claude/zentao-dev-workflow.home` | 3 | 发行版安装记录 |
| 脚本所在仓库 | 4 | 开发源 |
| 向上探测 | 5 | 最后回退 |

**问题**：旧版源码安装留下的用户级 JSON 指向旧目录时，会**覆盖**新 `.home`；新版本安装到新目录后，`.home` 已更新，但 `_home.py` 仍解析旧目录——混合状态。

## 3. 当前行为

### 首次安装
- 默认 `install.sh` 安装 Skill/Agents、写 `.home`、注册 Hook。
- `--with-mcp` 额外注册 MCP；旧实现用 `claude mcp add`，已存在时不会更新路径。

### 原目录升级
- Skill/Agents 覆盖；Hook 幂等替换；`.home` 重写；配置文件/数据库/execution 不动。
- 默认安装就是升级路径。

### 跨目录升级
- 旧实现只写 `.home`，不更新用户 JSON、Hook、MCP，也不迁移数据 → 混合状态/数据丢失风险。
- 无 `--migrate` 命令。

## 4. MCP / Hook 注册

- Hook：`~/.claude/settings.json` 的 `UserPromptSubmit`；`hitl_hook.py` 幂等合并/备份/卸载。
- MCP：`~/.claude.json` 的 `mcpServers.human-decision`；旧实现只 `claude mcp add`，路径变化不更新。
- 已运行的 Claude/cc-connect Session 不热加载 settings，需新会话或 `/new`。

## 5. 用户数据保护

- `install.sh` 不修改 `config/`、`.env`、`execution/`、SQLite；`hitl_hook` 备份 settings。
- 无统一状态检查、无迁移备份/回滚、无数据复制策略。

## 6. Windows / macOS

- Bash + Python；`native_root` 用 `pwd -W`（Windows）回退 `pwd`。
- 路径空格、盘符、反斜杠未系统测试；macOS 未实机验证。

## 7. 已发现问题

1. 用户级 JSON 覆盖 `.home`（跨目录混合）。
2. MCP 路径不随安装/迁移更新。
3. 无 `--migrate`，跨目录会丢数据或混合。
4. 无统一安装状态/健康检查（`--check` 仅环境检查）。
5. 无迁移备份/失败恢复/操作日志。
6. 旧 Hook 不热加载，无明确提示。
7. `--with-mcp` 非幂等路径更新。
8. 无 Windows 空格路径/跨目录自动化测试。

## 8. 最小改造方案

1. 新增 `scripts/install_manager.py`：`status` / `detect` / `sync-mcp` / `migrate`。
2. `install.sh`：`--upgrade`、`--migrate`、`--check` 接统一状态；默认安装拒绝跨目录混合。
3. 迁移：识别唯一旧根、备份用户配置、复制缺失数据（SQLite `backup`）、更新用户 JSON/.home/Hook/MCP、健康检查、失败回滚、保留旧目录。
4. MCP：仅更新 `human-decision` 一项，保留其他 MCP。
5. Hook：复用 `hitl_hook.py`，只维护自身项。
6. 测试：安装/重复/升级/跨目录/多旧根/数据保护/`--check` 只读/卸载。

## 9. 自动化覆盖

- `tests/test_install_flags.py`：8 项（安装、重复、升级、迁移、多根拒绝、MCP 保留、卸载、初始化/检查）。
- 源码全量 231，发行版全量 308，HITL 110。

## 10. 未完成真实验证

- macOS 实机；
- Windows 路径含空格/非系统盘的真实迁移；
- 生产用户配置的破坏性迁移（禁止；只在隔离用户目录测试）。
