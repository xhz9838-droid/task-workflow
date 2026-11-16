# 集成方案（Integration Plan）

## 1. 禅道 ↔ zentao-worker

| Conductor Task | 实现 | 复用点 | 约束 |
|---|---|---|---|
| `zt_list_my_tasks` | `python -I manage_tasks.py list --json --status wait,doing` | `ZenTaoClient.whoami` + `list_tasks(assignedTo=me, fetch_all=True)` | 身份取自 whoami，与 config.assignee 不一致则失败；去重；排除 done/closed |
| `zt_snapshot` | `task_detail(id)` | 已有 | 只展示禅道实际返回字段，缺失标"未提供" |
| `zt_start` | `manage_tasks.py start --task <id> --consumed <c> --left <l>` | 默认补回原指派人 + 读回核验 | consumed/left 必须由本人提供（钉钉 HUMAN 收集），否则暂停 |
| `zt_writeback` | `manage_tasks.py update --task <id> --fields '{"desc":...}'` | 统一 PUT + 读回 | **追加**而非覆盖 desc：先读原文，原文保留，在末尾追加带时间戳的进度段；失败先查详情再决定是否重试 |
| `zt_finish` | `manage_tasks.py finish ...` | 已有 | 仅在 HUMAN `finish_confirm` 通过且本人提供工时后 |

> 待确认：禅道 desc 为富文本，追加式写回会使描述增长。备选方案是只写任务"备注/历史"——需验证 REST 是否支持任务评论（Bug 的 `/comments` 已实证 404）。

## 2. Conductor 部署

- 方式：Docker Desktop 启动后 `docker compose -f docker/docker-compose-postgres.yaml up -d`（conductor-oss 官方仓库，固定 release tag）。
- 配置：`conductor.db.type=postgres`、`conductor.scheduler.enabled=true`；Postgres 数据卷持久化；仅监听 127.0.0.1。
- 备选（Docker 无法启动时）：Java 22 运行 Conductor server jar + 本机 Postgres（需安装，属新依赖，需确认）。
- Worker 通信：HTTP 轮询 `GET /api/tasks/poll/{taskType}` + `POST /api/tasks`；使用官方 `conductor-python` SDK（新 pip 依赖，装在独立 venv，**不污染**禅道 Skill 用的 Python313 全局环境；禅道调用仍以子进程 `python -I` 执行）。
- HUMAN 完成：`POST /api/tasks` 提交 `COMPLETED` + output（决策内容）。

## 3. Claude Code ↔ claude-runner

- 启动：`claude -p "<prompt>" --output-format stream-json --agents .claude/agents --add-dir <worktree> --permission-mode <受控模式> --allowedTools <白名单>`，记录 `session_id`。
- 恢复：`claude -p --resume <session_id> "<决策/修复指令>"`。
- 隔离：`git worktree add D:\WorkSpace\.worktrees\<repo>/zt-<id> -b ai/zt-<id> <base>`；**不触碰**主工作区的未提交修改（多数仓库当前有未提交文件）。
- 输出：结构化完成报告 JSON（文件清单、测试命令与结果、git diff 摘要），由 Main Agent 复核后作为 task output。

## 4. Jenkins ↔ jenkins-worker

现有 Job 复用结论：**不复用作测试**（全部为部署 Job）。方案：

1. 经批准后新建 1 个参数化 Pipeline Job `ai-test-runner`（不改全局配置、不装插件）：
   参数 `REPO_URL, GIT_BRANCH, GIT_COMMIT, ZENTAO_TASK_ID, WORKFLOW_ID, TEST_SCOPE`；阶段 Checkout → Build → Unit Test → Report(junit)。Git 凭据需新增一个 Job 级/Folder 级 Credential（需本人提供或管理员创建）。
2. 首次运行 `TEST_SCOPE=toolcheck`，只执行 `java -version / mvn -v / node -v / git ls-remote`，验证内置节点工具链和网络。
3. Worker 流程：`POST /job/ai-test-runner/buildWithParameters`（带 crumb）→ 读 `Location` 得 Queue ID → 轮询 `/queue/item/<id>/api/json` 得 build number → 轮询 `/job/.../<n>/api/json` 直到 `building=false` → 读 `result` + `/testReport/api/json` + `consoleText`（截断、脱敏）+ artifacts → 回传 Conductor。
4. 判定：SUCCESS 且测试报告存在且 failCount=0 → 通过；UNSTABLE → 交 QA Agent 分析；FAILURE/ABORTED/NOT_BUILT → 不通过；Jenkins 不可达/401/404 → HUMAN 阻塞，**不回退到任何其他 CI**。

## 5. 钉钉 ↔ dingtalk-adapter

- 前置：企业内部应用（AppKey/AppSecret、机器人 robotCode）、本人 userId、开启 Stream 模式与互动卡片回调权限 —— **当前全部未配置**。
- 发送：机器人单聊 `oToMessages/batchSend`（P0 可用 sampleMarkdown/ActionCard + 链接）；P2 升级为互动卡片。
- 接收：Stream 模式订阅卡片回调 → 校验 userId=本人 → 幂等键去重 → 写审计日志 `workers/dingtalk-adapter/audit.jsonl` → 完成 HUMAN 任务。
- P0 降级方案：在钉钉未配置前，HUMAN 任务可由本人在 Conductor UI 或 CLI 手动完成。

## 6. 仓库映射

新建 `.orchestration/config/workflow-config.yaml`：`禅道 project/execution → {backend, web, mobile 仓库路径, base 分支, Jenkins 测试参数}`。初始映射需本人确认（见 inventory E 节推测表）。
