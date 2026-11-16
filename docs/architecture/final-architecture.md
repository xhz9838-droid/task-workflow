# 最终架构（Final Architecture）

> 依据：`docs/execution/environment-inventory.md` 的实测结果。原则：优先复用、少量开发、可恢复、可验证。

## 1. 总体结构

```
                 ┌──────────── Conductor OSS（Docker + PostgreSQL，唯一编排/状态源）────────────┐
                 │  Scheduler(cron 10min) → ZentaoPollingWorkflow → ZentaoDevelopmentWorkflow   │
                 │  FORK/JOIN · RETRY · TIMEOUT · HUMAN · WAIT · 执行历史                       │
                 └───────▲─────────────▲──────────────▲───────────────▲─────────────────────────┘
                         │ poll/ack    │ poll/ack     │ poll/ack      │ HUMAN 完成信号
          ┌──────────────┴──┐ ┌────────┴────────┐ ┌───┴──────────┐ ┌──┴──────────────────┐
          │ zentao-worker   │ │ claude-runner   │ │ jenkins-     │ │ dingtalk-adapter    │
          │ (python -I)     │ │ (claude -p)     │ │ worker       │ │ (Stream 模式)       │
          └───────┬─────────┘ └───────┬─────────┘ └──────┬───────┘ └──┬──────────────────┘
                  │ import            │ git worktree      │ REST       │ OpenAPI / Stream
     ~/.claude/skills/zentao(_tasks)  D:\WorkSpace\<repo>  Jenkins     钉钉企业内部应用机器人
          → 禅道 10.0.0.172:3088      Main Agent+Subagents 10.0.0.172:3194
```

所有 Worker 运行在本机（Windows），以 HTTP 轮询方式连接 Conductor（无需对外暴露端口）。

## 2. 组件与复用边界

| 组件 | 复用 | 新增（最小） |
|---|---|---|
| 禅道 | `ZenTaoClient`、`manage_tasks.py`（start/finish/update）、write_guard、读回核验 | `manage_tasks.py list --json` 只读子命令（基于已有 `list_tasks`，不新建客户端）；zentao-worker 薄封装 |
| 编排 | Conductor OSS 官方镜像 + Postgres compose、内置 Scheduler、HUMAN 任务 | 2 个 Workflow JSON 定义 |
| AI 执行 | Claude Code CLI（`-p`/`--resume`/`--agents`/worktree）、全局 Agents | 项目级 7 个 Subagent 定义、claude-runner 薄封装（启动/恢复/产物收集） |
| CI | 公司 Jenkins、Pipeline/junit/git 插件、内置节点 | 1 个**测试专用** Pipeline Job（经审批后创建，不改全局配置）、jenkins-worker |
| 通知 | `dingtalk-message` Skill 的 API 知识 | dingtalk-adapter（发卡片 + Stream 回调 → 完成 HUMAN 任务） |
| 状态存储 | Conductor（Postgres） | **无**第二套状态库；仅本地审计日志文件 |

## 3. 关键设计决策

1. **测试与部署分离**：现有 16 个 Jenkins Job 都是 SSH 部署 Job，禁止作为自动测试触发。新增 `ai-test/<repo>` 测试 Pipeline（只 checkout + build + test + junit 归档，不部署）。现有部署 Job 只能在最终验收后、经钉钉人工批准时触发（P0 不涉及）。
2. **工作流唯一性**：Conductor `correlationId = zentao-task-<id>`；启动前按 correlationId 查询 RUNNING/PAUSED 实例，存在即恢复，不重复启动。
3. **长时等待不占进程**：L3 阻塞 → HUMAN 任务；claude-runner 在提交 `sessionId/worktree/branch` 到 task output 后退出；决策到达后 Dispatcher 用 `claude -p --resume <sessionId>` 恢复。
4. **禅道写入集中**：只有 zentao-worker 的 `writeback` 任务写禅道，且全部经现有 `task_update`（PUT）+ 读回核验；`task_finish` 仅在 HUMAN"确认完成"后执行；不自动 close。
5. **钉钉回调用 Stream 模式**：执行机在内网，不需要公网回调地址；回调验证 userId 白名单（仅本人）、按 `workflowId+taskRefName+decisionId` 幂等、写审计日志。
6. **Windows 适配**：Worker 统一使用 `C:\Users\eickoe\AppData\Local\Programs\Python\Python313\python.exe -I（即 python 命令，3.13.1，已实测；不用 python3 存根）`；路径用 Windows 形式传给 claude/git；worktree 放 `D:\WorkSpace\.worktrees\<repo>/zt-<id>`。

## 4. Workflow 草图

**ZentaoPollingWorkflow**（Scheduler 每 10 分钟 + 手动）
`zt_list_my_tasks` → `zt_classify`（研发/非研发、仓库映射、信息充分度、已有 workflow 检查）→ `DYNAMIC_FORK`（并发上限 1）启动/恢复 `ZentaoDevelopmentWorkflow` → 汇总通知。

**ZentaoDevelopmentWorkflow**（每任务一个）
```
zt_snapshot → claude_analyze(需求/架构/DDL/OpenAPI/计划) → HUMAN design_approval(钉钉)
 → zt_writeback(设计完成) → [P0 止于此 / P1 起] FORK(db, java, web, mobile) → JOIN
 → jenkins_test(unit) → jenkins_test(api/integration) → jenkins_test(e2e)
 → (失败: claude_fix 循环 ≤ N 次，超限 → HUMAN blocker)
 → acceptance_report → zt_writeback(交付报告) → HUMAN finish_confirm → zt_finish
```

## 5. 安全

- 凭据仅存于：禅道 `config.json`（已有）、`workers/.env`（gitignored，Jenkins/钉钉）；日志统一脱敏。
- Jenkins 使用独立低权限账号（建议，替换 admin Token）。
- 禁止任何生产部署；测试 Pipeline 不含 ssh/pm2 步骤。
