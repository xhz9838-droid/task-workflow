# P0 实施计划

**目标**：打通"一个真实本人禅道任务"的 拉取 → 分析 → 人工确认（Conductor HUMAN）→ 进度回写 闭环，并完成一次 Jenkins 测试 Job 的真实触发与结果回收。

## 前置决策（需本人提供/确认）

| # | 事项 | 原因 |
|---|---|---|
| D1 | 提供一个 POC 用的本人禅道任务（wait 或 doing） | 当前本人 wait/doing 任务为 0 |
| D2 | 确认仓库映射（POC 任务 → 哪个仓库/分支） | 现无可靠映射 |
| D3 | 是否批准在 Jenkins 新建 `ai-test-runner` Pipeline Job（仅 Job 级，不改全局） | 现有 Job 均为部署 Job |
| D4 | Jenkins 用于拉代码的 Git 凭据由谁创建 | Jenkins 中 0 个 Credential |
| D5 | 是否轮换 admin Token / 新建低权限账号 | 安全 |
| D6 | 允许启动 Docker Desktop 并部署 Conductor（本机，仅 127.0.0.1） | 目前 Stopped |
| D7 | 是否允许新增 pip 依赖 `conductor-python`（独立 venv） | 新依赖 |
| D8 | 钉钉企业内部应用凭据（P0 可延后，用 Conductor UI 代替） | 未配置 |

## 任务清单

- [ ] **T1 初始化项目仓库** | Claude | `task-workflow/`（git init、.gitignore 含 `.env`/日志）| 验收：git 仓库可用，无凭据入库
- [ ] **T2 部署 Conductor** | Claude | `.orchestration/docker/`（引用官方 compose，固定版本，开启 scheduler）| 验收：`/health` OK，重启容器后已定义 workflow 仍在
- [ ] **T3 禅道只读 list 入口** | Claude | `~/.claude/skills/zentao-tasks/scripts/manage_tasks.py` 新增 `list --json --status`（先备份；仅调用已有 `whoami`+`list_tasks`）+ 单测 | 验收：返回仅本人任务、翻页、去重；已有测试全通过
- [ ] **T4 zentao-worker** | Claude | `workers/zentao-worker/`（`zt_list_my_tasks`/`zt_snapshot`/`zt_writeback`；子进程调用 `python -I`）| 验收：真实拉取；写回经读回核验；原描述不被覆盖
- [ ] **T5 claude-runner（分析阶段）** | Claude | `workers/claude-runner/`、`.claude/agents/architect.md` | 验收：在 worktree 中生成 `docs/requirements|architecture|database|api|execution` 产物；session_id 入 Conductor output；可 `--resume`
- [ ] **T6 Workflow 定义** | Claude | `.orchestration/workflows/zentao-polling.json`、`zentao-development.json`（P0 截至 design_approval + writeback）| 验收：correlationId 去重；HUMAN 任务手动完成后流程继续
- [ ] **T7 jenkins-worker + 测试 Job（D3 批准后）** | Claude | `workers/jenkins-worker/`、`Jenkinsfile.ai-test`（toolcheck + unit）| 验收：记录 Queue ID→Build No→最终 result→测试报告；FAILURE/ABORTED 不判通过
- [ ] **T8 POC 端到端运行** | Claude + 本人 | — | 验收：Conductor 执行记录 + 禅道读回截图/JSON + Jenkins Build URL 作为证据

## 风险与依赖

| 风险 | 影响 | 应对 |
|---|---|---|
| 无本人可用任务 | POC 无法启动 | D1；或经本人同意改为以 Bug 走同样流程（zentao-bugs Skill） |
| Jenkins 内置节点工具链/网络未知 | 测试 Job 可能无法 checkout/构建 | toolcheck 先行；必要时请管理员加 Agent 节点 |
| 现有 Job 被误触发即部署 | 环境被改动 | jenkins-worker 只允许白名单 Job（`ai-test-*`） |
| 多数业务仓库有未提交修改 | 自动修改冲突 | 一律使用 worktree，不碰主工作区 |
| 业务仓库测试稀少（多个为 0） | 验收矩阵难以"全部通过" | P1 起由 QA Agent 补测试；如实报告覆盖情况 |
| 禅道 desc 追加写回膨胀 | 可读性 | 验证任务评论能力；不可用则精简追加格式 |
| Docker Desktop/WSL 无法启动 | Conductor 无法部署 | 备选 jar + Postgres（需确认依赖） |
| Windows 环境 | 路径/编码问题（GBK） | 子进程强制 `PYTHONIOENCODING=utf-8`，路径统一处理 |
| admin Token 泄露面 | 安全 | D5 |
