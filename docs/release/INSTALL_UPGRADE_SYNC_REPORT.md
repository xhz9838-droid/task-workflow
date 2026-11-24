# 源码与发行版同步报告（2026-11-24）

## 1. 变更文件

| 源码 | 发行版 | 说明 |
|---|---|---|
| `scripts/install_manager.py`（新增） | 同路径 | 状态/检测/MCP 同步/迁移 + 默认目录 `install-default` |
| `scripts/install.sh` | 同路径 | `--upgrade`/`--migrate`/`--default-dir`/`--dir`/统一 `--check`/MCP 同步 |
| `scripts/_config.py` / `doctor.py` / `jenkins_run.py` / `agent-manager/jenkins_adapter.py` | 同路径 | 支持 `config/.env`（默认目录） |
| `tests/test_install_flags.py` | 同路径 | 安装/升级/迁移/回滚（9 项） |
| `tests/test_install_default.py`（新增） | 同路径 | 默认目录/独立运行/空格路径/迁移（4 项） |
| `scripts/hitl_hook.py` | 同路径 | Hook 幂等合并（新增） |
| `docs/release/*.md` | 同路径 | 审计/设计/指南/验收/最终验收 |

源码 `install.sh` 保留开发布局（`.claude/skills/`、`workflow-register-project`），发行版 `install.sh` 为分发入口（`skill/`、`--check/--init-config/--upgrade/--migrate`）；两者行为契约一致。

## 2. 依赖与路径

- 无新增第三方依赖（Python 标准库 + PyYAML/mcp）。
- 无开发机绝对路径；Hook/MCP 命令由安装时 `native_root` 生成。
- 无凭据、`.env`、数据库、日志、临时文件同步。
- 发行版 `install.sh` 可从任意目录复制后独立执行（`WORKFLOW_HOME` 由脚本位置推导）。

## 3. 发行版测试

```text
python -I -m pytest                      → 313 passed
python -I -m pytest agent-manager/human_decision/tests → 110 passed
```

## 4. 未同步

- 源码个人/项目配置（`config/projects/*`、`config/users/*`、`config/adapters/*.local.yaml`）。
- 源码运行数据（`execution/`、`agent-manager/logs/`、`.env`）。
- 源码 `config/projects/jeebootx.yaml` 的他人未提交修改。

## 5. 状态

源码与发行版工作区均无本任务未提交文件（详见最终汇报）；未 push、未 Tag、未改 VERSION。
