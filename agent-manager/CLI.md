# P11.1 CLI 使用说明

> 统一命令行入口。复用现有 Runner / Monitor / StateManager / TaskRouter，不重复实现业务逻辑。
> 兼容 Windows 与 `python -I` 运行方式，仅使用 Python 标准库（PyYAML 为可选，缺失时降级）。

## 退出码约定

| 码 | 名称 | 含义 |
|---|---|---|
| 0 | `OK` | 成功 |
| 1 | `FAILED` | 执行失败 |
| 2 | `USAGE` | 参数错误 |
| 3 | `NOT_FOUND` | 任务不存在 |
| 4 | `LOCKED` | 已有运行实例 |
| 5 | `BLOCKED` | 阻塞（如任务已完成，不重复执行） |

## runner.py — 任务启动与状态查询

### 启动任务

```bash
python -I agent-manager/runner.py run --project jeebootx --task-id 3413
```

常用选项：

| 选项 | 说明 |
|---|---|
| `--project P` | 项目标识（必填） |
| `--task-id T` | 任务 ID（必填） |
| `--workdir DIR` | 工作目录（默认当前目录） |
| `--prompt TEXT` | 自定义 prompt（默认 `/zentao-dev-workflow {P} {T}`） |
| `--session-id ID` | 恢复的 Claude Code 会话 |
| `--dry-run` | **Mock 模式**：不启动真实开发任务 |
| `--force` | 覆盖重复/已完成检查（谨慎） |

分级相关（供 TaskRouter 判定 S/M/L）：

| 选项 | 说明 |
|---|---|
| `--level S\|M\|L` | 显式指定等级（覆盖自动分级） |
| `--description TEXT` | 任务描述（用于关键词分级） |
| `--files a.vue,b.ts` | 影响文件路径（逗号分隔） |
| `--files-count N` | 影响文件数 |
| `--repos a,b` | 受影响仓库（逗号分隔） |
| `--complexity low\|medium\|high` | 业务复杂度 |

用户指令优先（覆盖默认工作流）：

| 选项 | 效果 |
|---|---|
| `--no-subagents` | 不使用子 Agent |
| `--skip-build` | 跳过 Build |
| `--static-only` | 仅静态检查 |

通用：`--db PATH`（状态库）、`--json`（JSON 输出）、`--quiet`

### 查看状态

```bash
python -I agent-manager/runner.py status --task-id 3413 --project jeebootx
python -I agent-manager/runner.py status --task-id 3413 --json
```

输出：等级、状态、阶段、结果、起止时间、重试次数、Agent 运行表。
`--project` 省略时跨项目查最近记录。

### 查看历史

```bash
python -I agent-manager/runner.py history --task-id 3413
```

输出该任务所有执行记录（含失败/重试）。

### 列出执行记录

```bash
python -I agent-manager/runner.py list
python -I agent-manager/runner.py list --project jeebootx
```

## monitor.py — 运行监控

### 查看任务监控

```bash
python -I agent-manager/monitor.py --task-id 3413 --project jeebootx
```

输出**四概念分离**的健康快照：

```
Process Alive     : True/False      操作系统进程存活
Heartbeat         : ok/unavailable  管理器确认进度（无源时标 unavailable，不伪造）
Output Activity   : 0.0s 静默       距上次输出（仅告警，不据此杀进程）
Workflow Progress : QA1             是否推进到下一阶段
应终止            : False（…）
```

### 列出全部任务健康

```bash
python -I agent-manager/monitor.py --list
```

通用：`--db PATH`、`--json`、`--quiet`

## 示例

### Mock 验证（不启动真实任务）

```bash
python -I agent-manager/runner.py run \
  --project demo --task-id T-1 \
  --description "修改按钮文案 css 样式" \
  --files "src/views/Button.vue" --files-count 1 \
  --dry-run --db /tmp/test.db
```

输出：

```
任务分级: S
分类理由: 小范围修改（1 文件）；命中简单变更特征：文案、css、按钮；无数据库/API/安全/跨仓库风险
工作流:   direct
子 Agent: （无）
[dry-run] 未启动真实开发任务（Mock 验证模式）
```

### 高风险任务自动升级

```bash
python -I agent-manager/runner.py run \
  --project demo --task-id T-2 \
  --description "修复越权审批漏洞" \
  --files-count 1 --dry-run
# → 任务分级: M（单文件但含安全风险，不归 S）
```

### 用户指令优先

```bash
python -I agent-manager/runner.py run \
  --project demo --task-id T-3 \
  --description "重构模块" --files-count 15 \
  --no-subagents --skip-build --dry-run
# → 子 Agent: （无），预期测试无 build
```

## 边界行为

| 场景 | 退出码 | 行为 |
|---|---|---|
| 任务不存在 | 3 | 报错退出 |
| 任务已完成 | 5 | 拒绝重复执行（`--force` 可覆盖） |
| 任务正在运行（锁占用） | 4 | 拒绝重复启动（`--force` 可覆盖） |
| 无子命令/参数 | 2 | 打印帮助 |
| 中文路径/项目/任务 ID | 0 | 正常支持 |
| Windows 反斜杠路径 | 0 | 正常支持 |

## 测试

```bash
python -I agent-manager/tests/test_cli.py          # 41 PASS
python -I agent-manager/tests/test_integration.py  # 56 PASS
```

## 依赖

- Python 3.13+ 标准库（`argparse` / `sqlite3` / `subprocess` / `json`）
- `PyYAML` **可选**（缺失时配置降级为内置默认，不报错）
- `psutil` **可选**（有则用于 PID 检测，无则用 ctypes/kill 兜底）

## 限制（当前 BLOCKED）

| 项 | 说明 |
|---|---|
| `--watch` 持续监控 | 参数已预留，当前为单次快照 |
| 真实 Jenkins 构建 | 待 `ai-test-*` Job 就绪 |
| 真实禅道写入 | 待本人授权 |
| Token/工具调用统计 | 无可靠指标接口 |
