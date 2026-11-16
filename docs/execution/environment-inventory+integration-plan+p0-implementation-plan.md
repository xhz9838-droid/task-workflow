# 环境盘点（Environment Inventory）

> 调查时间：2026-11-16　调查方式：只读（未修改任何外部系统、未触发任何 Jenkins 构建、未对禅道做写操作）
> 本文不含任何账号密码、Token。凭据位置仅以路径说明。

## 0. 关键结论速览

| 项 | 状态 | 结论 |
|---|---|---|
| 执行机 | ⚠️ | **Windows 11 专业版 + Git Bash**（非 macOS），32 GB 内存，x86_64 |
| Claude Code | ✅ | 2.1.310，支持 `-p`、`--resume`、`--fork-session`、`--agents`、`--output-format stream-json`、`--add-dir` |
| 禅道 Skill | ✅ | 可用；身份 `xuhongzu` 已核实；**当前无 wait/doing 任务** |
| 禅道 list CLI | ⚠️ | `manage_tasks.py` 无 `list` 子命令；客户端 `list_tasks` 已有；`zentao-daily query` 只读可用但仅输出 Markdown |
| Jenkins | ⚠️ | 可达、2.555.2；Token 属于 **admin** 账号；16 个 Job **全部是 SSH 部署型 Job，没有测试 Job** |
| Conductor | ❌ | 未部署；Docker Desktop 已安装但处于 Stopped；`docker compose` 插件当前不可用 |
| 钉钉 | ❌ | `dingtalk-message` Skill 存在，但 `~/.dingtalk-skills/config` 不存在（未配置） |
| 工作目录 | ⚠️ | `D:/WorkSpace/task-workflow` 为空目录，不是 Git 仓库 |

## A. Claude Code

- 版本：`2.1.310 (Claude Code)`
- 无头/恢复能力：`-p/--print`、`--resume <session-id>`、`-c/--continue`、`--fork-session`、`--output-format stream-json`、`--input-format`、`--agents <json|file>`、`--allowedTools`、`--add-dir`、`--bare`
- 全局 `~/.claude/settings.json`：键 `autoMode, codemossProviderId, env, model, modelPicker`；**无 hooks、无 mcpServers 配置**
- 全局 Agents：`~/.claude/agents/` 下约 70 个通用 Agent（architect、code-reviewer、java-reviewer、tdd-guide、e2e-runner 等），**无本项目专用 Agent**
- 相关 Skills：`zentao`（共享包）、`zentao-tasks`、`zentao-bugs`、`zentao-daily`、`zentao-bug-autofix`、`zentao-iterations`、`zentao-requirements`、`zentao-testing`、`zentao-weekly`、`dingtalk-message`
- 当前项目目录：`D:/WorkSpace/task-workflow`（空，非 Git）

## B. 禅道

| 项 | 实际值 |
|---|---|
| Skill 路径 | `~/.claude/skills/zentao-tasks/`（SKILL.md / scripts/manage_tasks.py / references / tests） |
| 共享客户端 | `~/.claude/skills/zentao/_shared/`（`client_api.ZenTaoClient`，纯标准库，mixin 架构） |
| 配置文件 | `~/.claude/skills/zentao/_shared/config.json`（含凭据，gitignored，**不得复制/回显**） |
| Token 缓存 | `~/.claude/skills/zentao/_shared/.zentao_token.json` |
| 禅道服务 | `http://10.0.0.172:3088`，API 前缀 `/api.php/v1` |
| Python | `python` → `C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe`（3.13.1）；`py -0p` 同一解释器。⚠️ `python3` 是 WindowsApps 存根，**不可用** |
| 调用规范 | `python -I <script>`（已遵守，实测可运行） |
| manage_tasks.py 子命令 | `create / start / finish / close / update / conflict`（**无 list**） |
| 只读查询 | `ZenTaoClient.list_tasks(assignedTo=, fetch_all=True)`（自动翻页）、`task_detail`、`whoami`；`zentao-daily/scripts/daily_report.py --config <cfg> query`（Markdown 输出） |
| 身份确认方式 | `client.whoami()` → `GET /user` → `profile.account`；与 config 中 `assignee` 比对 |

实测结果（只读）：
- `whoami.account = xuhongzu`（研发角色），与配置 `assignee` 一致 ✅
- `list_tasks(assignedTo=xuhongzu)`：共 1 条，status=closed（#1856）；重复 ID 0；归属不一致 0
- **wait/doing 任务：0 条** → 当前不存在可直接用于 POC 的本人任务
- 本人 active Bug：7 条（市场系统 6、分包安全评价 1）
- Skill 关键约束（已读取并将严格遵守）：字段编辑只用 `PUT /tasks/<id>`；状态流转只用 start/finish/close 动作端点；start 会清空 assignedTo，需传 `realAssignedTo`（CLI 默认自动补回）；start 的 consumed/left 不能同时为 0；finish 需 `finishedDate`；不编造工时。

## C. Jenkins

| 项 | 实际值 |
|---|---|
| 地址 | `http://10.0.0.172:3194/`，从执行机可达（匿名 403，约 0.16s） |
| 版本 | Jenkins 2.555.2，Jetty 12.1.8 |
| 认证 | 所给 Token 与用户名 `admin` 匹配（`whoAmI` authenticated=true）；`cc`、`xuhongzu` 均 401 |
| 节点 | 仅 `Built-In Node`（Linux amd64，2 executors，label `built-in`），**无独立 Agent** |
| Folder / Multibranch | 无 |
| 系统凭据存储 | 全局域内 **0 个 Credentials** |
| 插件（相关） | workflow-aggregator（Pipeline）、workflow-multibranch、git 5.10.1、junit、gradle、generic-webhook-trigger、credentials-binding、publish-over-ssh、ssh-slaves、build-timeout、timestamper、pipeline-graph-view。**未安装**：jacoco、sonar、htmlpublisher、nodejs、docker-workflow、allure、钉钉插件 |

Job 清单（全部为"SSH 到目标机 → cd 部署目录 → git pull → 构建 → 重启"模式）：

| Job | 类型 | 参数 | 触发 | 构建特征 | 最近构建 |
|---|---|---|---|---|---|
| ct-jeebootx-sanitation | FreeStyle | BRANCH_NAME | GenericTrigger | mvn `-Dmaven.test.skip` | #150 SUCCESS 11-13 |
| ct-jeebootx-ui | Pipeline | BRANCH | — | npm + pm2 | #2 FAILURE 10-24 |
| ct-jeebootx-wflow-platform | FreeStyle | BRANCH_NAME | GenericTrigger | mvn skip test | #4 SUCCESS 09-15 |
| hermes-rest | FreeStyle | — | — | ssh | #10 SUCCESS 06-29 |
| jeebootx-ui | FreeStyle | — | GenericTrigger | npm | #161 SUCCESS 11-13 |
| mock-platform | FreeStyle | — | — | pnpm + pm2 | #7 SUCCESS 11-04 |
| qcc-crawl | FreeStyle | — | — | ssh | #3 SUCCESS 08-11 |
| ruxus / ruxus-ui | FreeStyle | — | — | ssh / npm | SUCCESS 09 |
| ruxus-mastra / -124 | FreeStyle | — | — | pnpm + pm2 | SUCCESS / ABORTED |
| yqyc-ai | FreeStyle | BRANCH_NAME | GenericTrigger | mvn skip test | #307 SUCCESS 11-11 |
| yqyc-ai-ui | FreeStyle | — | — | npm | #359 SUCCESS 10-13 |
| yqyc-ai-mastra-15 / -230 | FreeStyle | — | — | pnpm + pm2 | SUCCESS / FAILURE |
| yqyc-ui-app | FreeStyle | — | — | npm | #163 SUCCESS 09-02 |

**结论**：
1. 没有任何 Job 执行单元测试/接口测试/E2E，也没有 junit 发布器；Maven Job 全部显式跳过测试。
2. 触发任何现有 Job 等同于**向目标环境部署**，与"禁止未经批准的部署作为自动测试"冲突 → **现有 Job 不能作为测试 Job 复用**，只能作为"测试通过后经人工批准的部署"环节复用。
3. Jenkins 侧无 Git 凭据、只有内置节点，内置节点上的 JDK/Maven/Node 工具链及对 GitLab/Codeup 的网络可达性**未验证**（需跑一次最小 Pipeline 才能确认，属于新建 Job，需审批）。
4. 当前仓库（task-workflow）无对应 Job；业务仓库对应关系见 E 节。

## D. Conductor / Docker

| 项 | 实际值 |
|---|---|
| Docker CLI | 29.7.2 |
| Docker 引擎 | Docker Desktop（WSL2 发行版 `docker-desktop` 状态 **Stopped**），`npipe` 不可连接 |
| docker compose | 当前报 `unknown command`（Desktop 启动后通常随附，需复核） |
| Java | 22.0.2（可作为非 Docker 方案运行 Conductor Server jar 的备选） |
| Redis | `D:\Redis-x64-5.0.14.1` 存在（本次未使用） |
| Conductor OSS 能力（官方文档） | Workflow / Fork-Join / Retry / Timeout / HUMAN 与 WAIT 任务（外部 API 信号完成）/ 内置 Scheduler（`conductor.scheduler.enabled=true`，Quartz 6 位 cron，`/api/scheduler`）/ PostgreSQL 持久化（`docker/docker-compose-postgres.yaml`） |

## E. Git

- 工作目录 `D:/WorkSpace/task-workflow`：**非 Git 仓库，空目录，无 CI 文件**
- 业务仓库位于 `D:\WorkSpace\`（共约 30 个）。与本人禅道产品可能相关的仓库（**映射为推测，需本人确认**）：

| 仓库 | 当前分支 | 未提交文件 | 远端 | CI 文件 | 构建 | 测试文件数 | 推测对应 |
|---|---|---|---|---|---|---|---|
| yqyc-ai | master-codeup | 6 | 内网 10.11.139.41 | .gitlab-ci.yml | pom.xml + package.json | 15 | 市场系统 / Jenkins `yqyc-ai` |
| yqyc-ai-ui | kehu0820 | 1 | codeup.aliyun.com | .gitlab-ci.yml | package.json | 0 | 市场系统 / `yqyc-ai-ui` |
| ai-agent-service | master | 5 | codeup.aliyun.com | — | package.json | 14 | `yqyc-ai-mastra-*` |
| subcontract-eval | dev | 2 | gitlab.cscec3b-iti.com | — | pom.xml | 0 | 分包安全评价（无 Jenkins Job） |
| sub-safety-evaluation-front | pre | 0 | gitlab.cscec3b-iti.com | — | package.json | 0 | 分包安全评价 Web |
| sub-safety-evaluation-h5 | pre | 0 | gitlab.cscec3b-iti.com | — | package.json | 0 | 分包安全评价 移动 H5 |
| equipment-guard | maintenance_dev | 1 | gitlab.cscec3b-iti.com | .gitlab-ci.yml + Jenkinsfile | pom.xml | 8 | 大型设备管理 |

- ⚠️ gitlab.cscec3b-iti.com 的多个 remote URL **内嵌了凭据**（输出时已掩码），属于安全风险。
- `zentao-bug-autofix/config.json` 中已有 `product_project_map`（仅"智慧环卫"一项，路径为 `/workspace/...` 的旧路径，与本机不符）。

## F. 安全事项（需本人知悉）

1. Jenkins Token 属于 **admin** 且已在对话中明文出现：建议轮换，并为本工作流新建最小权限账号（Job 级 Build/Read 权限）。
2. 调查过程中禅道 config 的一个嵌套密码字段曾出现在本地工具输出中（脚本脱敏只处理了顶层键），未写入任何文件/日志；如有顾虑建议修改密码。
3. 多个 Git remote 内嵌凭据，建议改用凭据管理器。

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

