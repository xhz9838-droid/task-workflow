# 安装/升级验收（2026-11-24）

## 1. 自动化

| 范围 | 结果 |
|---|---|
| 源码全量 | **231 passed** |
| 发行版全量 | **308 passed** |
| 发行版 HITL | **110 passed** |
| 安装/迁移专项 | `tests/test_install_flags.py` **8 passed** |

覆盖：

- 全新安装、重复安装、原目录升级、跨目录迁移、迁移后再次升级；
- 多个旧根拒绝（`MULTIPLE_OLD_ROOTS`）；
- MCP 只更新自身、保留其他 MCP；
- Hook 安装/重复/升级/卸载，保留其他 Hook；
- `--check` 只读、`--init-config` 不安装；
- 迁移数据：`config/projects`、`.env`、`execution`、SQLite；
- 用户 JSON 其他字段保留。

## 2. Windows 实际测试

隔离临时用户 + 临时 runtime（`tests/test_install_flags.py` 子进程）：

| 项 | 结果 |
|---|---|
| 首次安装 | PASS |
| 重复安装 | PASS（Hook 不重复） |
| 原目录升级（Hook 路径替换） | PASS |
| 跨目录迁移 | PASS（`.home`/用户 JSON/Hook/MCP 全部新根） |
| 多旧根拒绝 | PASS |
| 数据保留 | PASS（config/.env/execution/DB） |
| 卸载 | PASS（只删自身） |
| `--check` | PASS（只读；输出组件状态） |

另有真实用户级 Hook 激活验证（源码 runtime）：status `ok`；真实 cc-connect 新会话 HITL 回复 `input_tokens=0 output_tokens=0`（无模型 turn）。

## 3. macOS

**NOT_TESTED**：当前环境无 macOS 实机。实现仅依赖 bash/Python/`pwd`/`sqlite3`，未发现平台专属命令；路径空格/权限仍需实测。

## 4. 真实环境边界

- 未对生产用户配置执行迁移（禁止）；迁移测试均在隔离临时用户目录。
- 未修改 cc-connect 配置，未停止任何 Session。
- 未 push/Tag/发布。
- 当前真实机器 `.home`/用户 JSON/MCP/Hook 指向源码 runtime；发行版 `--check` 会显示 `PATH_MISMATCH`，属预期（发行版不是当前运行时根）。

## 5. 结论

- 安装、原目录升级、跨目录迁移、状态检查、Hook/MCP 同步、数据保护：**PASS（Windows 隔离）**；
- macOS：**NOT_TESTED**；
- 真实用户配置迁移：未执行，不建议在生产配置上首次试跑。
