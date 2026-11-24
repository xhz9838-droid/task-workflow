# 安装/升级/迁移设计（2026-11-24）

## 1. 组件

| 组件 | 职责 |
|---|---|
| `scripts/install.sh` | 命令入口；Skill/Agents 部署；调用管理器 |
| `scripts/install_manager.py` | 状态检查、旧根识别、跨目录迁移、MCP 同步 |
| `scripts/hitl_hook.py` | Hook 幂等合并/卸载/状态 |
| `_home.py` | 运行时根解析（未改优先级） |

## 2. 命令

| 命令 | 行为 |
|---|---|
| `install.sh` | 首次安装/原目录升级；检测到其他旧根则拒绝并提示 `--migrate` |
| `install.sh --upgrade` | 原目录升级（与默认一致） |
| `install.sh --migrate` | 跨目录迁移：识别旧根、复制数据、更新全部指针 |
| `install.sh --check [--json]` | 只读状态检查 |
| `install.sh --init-config` | 只初始化配置 |
| `install.sh --with-mcp` | 安装 + 更新 MCP（保留其他 MCP） |
| `install.sh --uninstall` | 移除自身 Hook/Skill/Agents/.home |
| `install.sh --link` | Skill 软链模式（保持） |

参数冲突（`--migrate --upgrade`）返回 2。

## 3. 安装状态

`status` 真实读取文件与注册信息，输出：

- `INSTALLED` / `NOT_INSTALLED`
- `UPDATE_AVAILABLE`（安装副本与运行时源不一致）
- `PATH_MISMATCH`（`.home` 不符）
- `CONFIG_INCONSISTENT`（用户 JSON 不符）
- `HOOK_MISMATCH` / `MCP_MISMATCH`
- `DEGRADED`（依赖/运行时/组件异常）

每个检查含 Status/Path/Fix。

## 4. 跨目录迁移流程

1. `detect` 从 `.home`、用户 JSON、Hook、MCP 收集旧根；只接受存在的有效根。
2. 多个旧根 → `MULTIPLE_OLD_ROOTS`，拒绝猜测，不做修改。
3. 备份 `.home`、用户 JSON、settings、`~/.claude.json`。
4. 复制旧根缺失数据到新根：
   - `config/`（只补缺失文件，不覆盖新配置）
   - `.env`（新根缺失时）
   - `execution/`（新根缺失时）
   - `agent_manager.db`（SQLite `backup` API，在线一致快照）
5. 更新用户 JSON `workflow_home`（保留其他字段）。
6. 写 `.home`。
7. Hook：`hitl_hook.install` 新路径，保留其他 Hook。
8. MCP：只替换 `mcpServers.human-decision` 的 command/args；保留其他 MCP。
9. 健康检查；失败恢复备份文件，保留旧版本目录与已复制数据。
10. 写 `~/.claude/zentao-dev-workflow.migrate.json` 操作日志。

## 5. 安全边界

- 不删除旧版本目录。
- 不覆盖旧 `.env`/config/DB；新根已有数据不覆盖。
- 不修改 cc-connect 配置。
- 不停止 Claude/cc-connect/Agent。
- 用户 JSON/Hook/MCP 均为“读-改-写 + 备份”，不整文件覆盖。
- 迁移后的新会话才加载 Hook；提示 `/new`。

## 6. 兼容性

- 保留默认安装、`--check`、`--init-config`、`--with-mcp`、`--uninstall`、`--link` 语义。
- 新增 `--upgrade`（默认等价）、`--migrate`、`--json`（check）。
- 源码/发行版两套布局（`skill/` 与 `.claude/skills/`）由 `_skill_src` 自适应。
