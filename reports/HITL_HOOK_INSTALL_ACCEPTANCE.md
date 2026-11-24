# HITL Hook 安装与发行版集成验收（2026-11-24）

- 结论：**安装集成 PASS（Windows 隔离用户）；macOS NOT_TESTED；真实 cc-connect 新会话隔离待复测**

## 1. 实现

| 文件 | 作用 |
|---|---|
| `scripts/hitl_hook.py` | 幂等合并 `~/.claude/settings.json` 的 `UserPromptSubmit`；保留其他 settings/hooks；备份；状态检查；卸载只删自身 |
| `scripts/install.sh` | 默认安装/升级自动注册 Hook；`--check` 显示 Hook 状态；`--init-config` 不安装；`--with-mcp` 保持安装+MCP+Hook；`--uninstall` 移除 Hook |
| `agent-manager/human_decision/prompt_router.py` | Hook 实际路由逻辑；设置自身 `WORKFLOW_HOME`；记录 `logs/hitl-prompt-router.log` |

Hook 注册格式：

```json
{"hooks":{"UserPromptSubmit":[{"hooks":[
  {"type":"command","command":"python -I \"<WORKFLOW_HOME>/agent-manager/human_decision/prompt_router.py\""}
]}]}}
```

## 2. 参数契约

| 参数 | 行为 |
|---|---|
| 无参数 | 安装/升级 Skill+Agents、写 `.home`、注册 Hook |
| `--check` | 只读；输出 Hook 状态（not_installed/ok/mismatch/error） |
| `--init-config` | 只生成 `hitl.local.yaml`，不安装、不改 settings |
| `--with-mcp` | 默认安装 + 注册 MCP（Hook 同时注册） |
| `--uninstall` | 移除本工作流 Hook、Skill、Agents、`.home`；保留其他配置 |

## 3. 安装测试

隔离临时 `USERPROFILE`/`HOME` + 临时 runtime，未触碰真实用户配置：

| 测试 | 结果 |
|---|---|
| 默认安装注册 Hook | PASS |
| 重复安装不重复注册 | PASS |
| 升级替换旧 Hook 路径 | PASS |
| 卸载只移除本工作流 Hook，保留其他 Hook/model | PASS |
| `--init-config` 不安装、不写 settings | PASS |
| `--check` 只读 | PASS |

自动化：`tests/test_install_flags.py` **5 passed**；发行版全量 **305 passed**，HITL **110 passed**。

## 4. 当前用户环境激活

- `~/.claude/settings.json` 已合并 Hook（安装前备份 `settings.json.bak.<ts>`）；
- 其他 keys（model/env/plugins 等）保留；
- `hitl_hook.py status` → `state=ok`，command 指向
  `D:/WorkSpace/task-workflow/agent-manager/human_decision/prompt_router.py`；
- 已安装 Hook 指向**当前源码 runtime**（本机 `.home` 为源码根），不是发行版目录。

## 5. 平台

- Windows：隔离用户安装/升级/卸载通过；
- macOS：未在真机执行，标记 **NOT_TESTED**。实现使用 bash + Python + `pwd`，未发现平台特定命令。

## 6. 限制

- Hook 只阻止 Claude 模型 turn；cc-connect 仍会启动 Claude 进程。
- 已存在的 cc-connect Agent 进程在 Hook 安装前启动，不会热加载 settings；必须新建会话后才生效。
