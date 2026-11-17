# 发版流程（Release Process）

> 通用核心能力，工具：`scripts/release_run.py`（编排）+ `scripts/jenkins_run.py`（构建）+ `scripts/zt.py`（回写）。

## 流程

```text
plan（发版计划+门禁快照）→ gate（真实测试证据门禁）→ trigger（白名单构建）
→ status（结果判定）→ report（发版报告）→ 禅道回写（progress/worklog）
```

## 硬约束

1. **只触发白名单 Job**（`config/adapters/jenkins.yaml → jobs[]`）。
2. **部署类 Job（`deploy_jobs[]`）禁止自动触发**：必须经 HITL P0 人工决策并以
   `--decision <DEC-ID>` 显式授权，全链路留审计。
3. **发版门禁以真实测试为准**：kind ∈ `real_api/e2e/unit/integration` 且通过才放行；
   仅 `review`（代码审查）不能作为功能正确性证据；`BLOCKED/NOT_RUN` 如实呈现。
4. **构建结果以 Jenkins 最终 result 为准**：FAILURE/ABORTED/NOT_BUILT 绝不判通过；
   UNSTABLE 必须分析。
5. **工时日志（worklog）耗时必须人工提供**（PRD 5.5 禁止猜填），已完成内容写日志的
   `work` 字段（不是 desc）。

## 命令

```bash
python -I scripts/release_run.py plan    --task <id> --project <key> [--version v1.2.3]
python -I scripts/release_run.py gate    --task <id> --project <key>
python -I scripts/release_run.py trigger --task <id> --project <key> --jobs <csv> [--branch b] [--commit c] [--decision DEC-x] [--force]
python -I scripts/release_run.py status  --task <id> --project <key> [--jobs <csv>]
python -I scripts/release_run.py report  --task <id> --project <key> [--writeback]

# 禅道回写
python -I scripts/zt.py progress --task <id> --stage release --text "发版说明…"
python -I scripts/zt.py worklog  --task <id> --date 2026-11-17 --consumed 2 --work "已完成…" [--left 8]
```

## 已知约束（如实）

- 工时日志走 MVC 端点 `task-recordWorkhour-<id>.html`（REST 无工时端点，实测 404）；
  受迭代 ACL 约束，账号无权限时返回『您无权访问该迭代』——须先解决项目/迭代成员权限。
- 发版 Job 候选（jeebootx 系构建）：`ct-jeebootx-sanitation` / `ct-jeebootx-ui` /
  `ct-jeebootx-wflow-platform` / `jeebootx-ui`；白名单扩项需人工确认。
