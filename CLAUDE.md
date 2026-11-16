# task-workflow：禅道任务驱动的多 Agent 研发工作流（第一阶段）

本仓库是**编排仓库**：存放设计文档、执行状态、Agent 定义和脚本。业务代码在四个业务仓库，通过 Git Worktree 修改。

## 角色

- **Main Agent（本会话）**：唯一协调者。负责拆分任务、分派 Subagent、复核交付、更新执行状态、禅道回写、CC Connect 人工决策。
- **Subagents**：`.claude/agents/*.md`，各自只改自己所有权范围内的文件，返回结构化报告（见下）。

## 业务仓库（主工作区只读，禁止改动其未提交文件）

| 代号 | 路径 | 角色 |
|---|---|---|
| sanitation | `D:/WorkSpace/jeebootx/jeebootx-sanitation` | 环卫业务后端（Java） |
| upms | `D:/WorkSpace/jeebootx/jeebootx` | 平台/权限/BPM 后端（Java） |
| web | `D:/WorkSpace/jeebootx/jeebootx-ui` | Web 前端 |
| app | `D:/WorkSpace/jeebootx/jeebootx-app` | 移动端（默认只读审查） |

- 所有开发在 worktree：`D:/WorkSpace/.worktrees/<代号>-zt<任务ID>`，分支 `ai/zt-<任务ID>`，基于各仓库当前 `dev`。
- 遵守各业务仓库自身的 `CLAUDE.md` / `AGENTS.md`。

## 状态文件（唯一可信状态源，不以聊天记录为准）

- `execution/<id>/run-state.json`：阶段、各 Agent 状态、worktree、分支、commit、Jenkins Build、阻塞、最近验收结果。
- `execution/<id>/session.json`：Claude Session ID、CC Connect 项目/会话 key（不含 token）。
- `docs/<id>/progress.md`、`decisions.md`、`acceptance-matrix.md`。
- `execution/<id>/audit.jsonl`：关键操作审计（禅道写、Jenkins 触发、人工决策），由 `scripts/audit.py` 追加。

每个里程碑结束必须更新 run-state.json 与 progress.md。

## 硬约束

1. **禅道**：只用 `~/.claude/skills/zentao-tasks`（`python -I`）。只操作本人任务。字段编辑只用 `update`（PUT）+ 读回核验；进度**追加**到 desc，不覆盖原文；不编造工时/日期/百分比；`start` 的 consumed/left 由本人提供；`finish` 仅在本人通过 CC Connect 明确确认后；**永不 close**。
2. **Jenkins**：只允许触发 `ai-test-runner`（`scripts/jenkins_run.py` 内置白名单）。现有部署 Job 一律禁止触发。结果以最终 `result` + 测试报告为准；FAILURE/ABORTED/NOT_BUILT 绝不判为通过；UNSTABLE 必须分析。
3. **人工决策**：经现有 CC Connect（`scripts/notify.sh`）发送，消息必须带 TaskID、SessionID、BlockerID、阶段。设计未确认前不写业务代码。
4. **凭据**：不写入仓库、日志、文档、Jenkins 参数。本地凭据只放 `.env`（gitignored）。
5. **如实报告**：测试未跑就说未跑，失败就贴失败；不伪造结果。

## 结构化 Agent 报告格式

`execution/<id>/agent-reports/<agent>-<seq>.json`：
```json
{"agent":"java-backend","task_ids":["B1"],"status":"done|blocked|failed",
 "worktree":"...","branch":"...","commit":"...",
 "files_changed":["..."],"tests":[{"cmd":"...","result":"pass|fail|not_run","evidence":"..."}],
 "blockers":[{"id":"BLK-...","level":"L1|L2|L3","summary":"..."}],"notes":"..."}
```

## 问题分级

- L1 编译错误/常规 Bug：Agent 自行修复。
- L2 多个可行技术方案：在已确认约束内自选，记 ADR 到 `docs/<id>/decisions.md`。
- L3 业务规则不清、DDL 重大变更、API 契约破坏、数据/权限风险、基础设施不可用：暂停受影响 Agent，写 run-state 阻塞，CC Connect 请求决策。
