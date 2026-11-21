# Workflow 多任务真实执行专项验收报告

- 日期：2026-11-21
- 源码根：`D:/WorkSpace/task-workflow`
- 验收对象：`/zentao-dev-workflow jeebootx 3442 3443 3444 3445`
- 约束遵守：未改全局安装、未重写调度/HITL/SQLite/门禁、未提交 Git、未打 Tag、未触发 Jenkins、未重复派发运行中任务
- 结论：**可受控接入，串行多任务规划与企业内复用可用；跨任务真实派发与并行执行未完成验收**

---

## 1. 真实状态核查（第一阶段）

### 1.1 禅道任务

| 任务 | 名称 | 状态 | 指派 | 执行 | 截止 | 剩余 |
|---|---|---|---|---|---|---|
| 3442 | 产品管理改造 | doing | xuhongzu | 智慧环卫202611 | 2026-11-25 | 8h |
| 3443 | 参数管理改造 | doing | xuhongzu | 智慧环卫202611 | 2026-11-25 | 8h |
| 3444 | 设备列表与详情改造 | doing | xuhongzu | 智慧环卫202611 | 2026-11-25 | 8h |
| 3445 | 工作记录 | doing | xuhongzu | 智慧环卫202611 | 2026-11-25 | 8h |

证据：`python -I scripts/zt.py detail --task <id>` 只读返回。

### 1.2 SQLite / DAG / 运行中的 Agent

| 任务 | execution | workflow_status | 节点状态 | 运行中的 Agent |
|---|---|---|---|---|
| 3442 | 17 | PENDING / dispatch-bootstrap | A1–A3、B1 DONE；**B2 RUNNING**；C1–D2 pending | `dw-web-frontend`，agent_id `a746a21db52e96082`，attempt `att-b2-28a76712` |
| 3443 | 无 | — | 无执行记录 | 无 |
| 3444 | 无 | — | 无执行记录 | 无 |
| 3445 | 无 | — | 无执行记录 | 无 |

补充证据：

- `agent_runs` 为空（CLAUDE_TOOL 后端只有 agent_id，无 pid）；`task_locks` 为空；`pending_writes` 为空。
- `execution_events` 共 16 条，最近事件为 15:38:36 `node_dispatch_updated`（B1 DONE）。
- 3442 的 `run-state.json`：`execution_id=17`、`state_source=sqlite`；节点快照与 SQLite 逐项一致（未派发节点按 pending 计）→ **一致：True**。
- 3442 已有 DAG（9 节点）；3443–3445 在本次接入前**无 DAG、无执行记录**。
- 显式依赖：3442 的 DAG 无 `depends_on_tasks`；3443–3445 原无 DAG。开发计划
  `jeebootx-sanitation/docs/51-HW-设备管理板块调整-开发执行计划.md §13` 明确：
  `3442 → 3443`、`3443 → 3444 参数弹窗`、`3444 Tab 壳 → 3445 前端`。

### 1.3 潜在文件冲突

| 任务 | 主要改动面 | 冲突判断 |
|---|---|---|
| 3442（运行中） | 后端 `DevProduct*`；前端 `views/device/product/**`、`api/device/product.ts` | — |
| 3443 | 后端 `DeviceParam*`、`DevDeviceAccessController`；前端 `views/device/param/**`、`DeviceParamDialog.vue` | 与 3442 的参数模板入口相关；与 3444 参数弹窗相关 → 已排 3442→3443 |
| 3444 | 后端 `DevDevice*`；前端 `views/device/device/index.vue`、`detail.vue` | 参数弹窗依赖 3443；详情 Tab 壳被 3445 依赖 → 3443→3444 |
| 3445 | 后端 `DevDeviceWorkRecord*`、`DeviceTcpBusinessService`；前端 `WorkRecordTable.vue`、`workRecord.vue` | 前端依赖 3444 的 4 Tab 壳；心跳钩子与设备服务相邻 → 3444→3445 |

结论：四个任务存在**文件级耦合**，不能按"无显式依赖"视为可安全并行。当前保守串行顺序与开发计划一致。

---

## 2. 多任务规划验证（第二阶段）

### 2.1 接入动作（未派发、未建 execution）

为 3443/3444/3445 补充了**规划骨架** `execution/jeebootx/{3443,3444,3445}/tasks.yaml`：

- 节点结构复用现有 A1/A2/A3/B1/B2/C1/C2/D1/D2；
- `depends_on_tasks` 按开发计划 §13：3443→3442、3444→3443、3445→3444；
- `files_owned` 仅写计划中已明确的主要文件族，其余留待 A2 细化；
- **未创建 execution、未登记派发、未启动任何 Agent**。

3442 的 DAG/状态/run-state **未修改**。

### 2.2 batch-plan 结果

```text
waves: [["3442"], ["3443"], ["3444"], ["3445"]]
execution_order: ["3442", "3443", "3444", "3445"]
errors: []
3442: status=in_progress, B2=running
3443/3444/3445: status=not_started, deps 分别为 3442/3443/3444
```

- 运行中的 3442 被识别为 `in_progress`，未产生任何派发动作。
- 重复执行 batch-plan 两次，输出**逐字节一致**（幂等）。
- 执行前后 SQLite 签名一致：`06a38a0e…6b58` → `06a38a0e…6b58`。
- 3443/3444/3445 的 execution 查询仍为空（未建空壳）。
- 运行中任务没有新增 dispatch 行：B2 仍只有 `att-b2-28a76712` 一条。

### 2.3 依赖异常拒绝

| 场景 | 命令 | 结果 |
|---|---|---|
| 循环依赖 | `batch-plan --depends "3442:3443"`（叠加已有 3443:3442） | rc=1，`DEP_CYCLE` |
| 未知依赖 | `batch-plan --depends "3445:9999"` | rc=1，`DEP_UNKNOWN` |
| 并行开关 | `batch-plan --parallel` | 波次不变；`execution_order=[]`、`parallel_within_wave=true` |

---

## 3. 现有任务接入与真实执行（第三阶段）

| 要求 | 实际处置 | 结果 |
|---|---|---|
| 复用运行中的 3442 | 只读查询；未重建 DAG、未改 run-state、未派发 | ✅ |
| 已有 DAG 的任务复用 DAG | 3442 DAG 与 SQLite 状态直接复用 | ✅ |
| 无 DAG 的任务补充规划 | 3443–3445 写入规划骨架 + 依赖 | ✅（规划层） |
| 已完成任务保留验收 | 无已完成任务 | N/A |
| 失败/中断任务从原状态恢复 | 3442 未失败；无其他中断执行 | N/A |
| 重复入口不重复派发 | batch-plan ×2 + DB 签名一致 | ✅ |
| 逐任务跟踪执行/测试/回写 | 3442 保留原执行链路；3443–3445 未派发 | PARTIAL |

**没有启动 3443/3444/3445 的任何 Agent**：这三个任务在禅道为 doing，本地无执行记录；按本轮约束"不允许重新启动整个工作流"，只做了规划接入，实际派发需在各自设计确认后由正常流程启动。

3442 的真实执行证据（既有，非本轮新建）：

- A1/A2 `dw-architect`、A3 `main`、B1 `dw-java-backend` 已 DONE，均有 agent_id/attempt_id；
- B2 `dw-web-frontend` RUNNING（agent_id `a746a21db52e96082`）；
- B1 与 B2 同时于 15:25:30 派发（任务内并行），B1 15:38:36 DONE，B2 仍运行；
- `dispatch.py plan`：`executable=[]`，`in_progress=[B2]`，未重复派发；
- `dispatch.py gate`：`ok=false`，原因 `NODE_INCOMPLETE`（B2 running + C1/C2/D1/D2 pending）→ 未完成/运行中正确阻止整体结束。

---

## 4. 异常与恢复验证（第四阶段，隔离模拟）

| 验证点 | 证据 | 结果 |
|---|---|---|
| 任务失败不阻塞独立任务 | `test_one_task_attention_does_not_block_others` | PASS |
| WAITING_HUMAN 不阻塞独立任务 | `test_waiting_human_does_not_block_other_tasks` | PASS |
| 决策完成后恢复 | `test_waiting_human_resumes_after_decision`；HITL `test_full_flow_decided`、`test_complete_flow` | PASS |
| Agent 中断恢复原任务 | HITL `test_recovery_after_restart`；`test_resume_checkpoint_when_tool_suspended`、`test_resume_idempotent` | PASS |
| 重复启动不重复派发 | batch-plan ×2 幂等；`dispatch plan` 对 RUNNING 节点不再列入 executable | PASS |
| SQLite 与 run-state 一致 | 3442 逐节点比对 True | PASS |
| 回写失败重试 | `pending_writes` 为空；`test_notify_failure_keeps_decision_waiting`、gate 的 pending_writes 测试 | PASS（隔离） |
| 未完成/存活 Agent/未刷写阻止完成 | 3442 `gate` rc=1；`test_gate_blocks_incomplete_and_pending_writes` | PASS |

测试执行证据：

- `tests/test_batch_plan.py` + `tests/test_dispatch_state.py`：**18 passed**
- `human_decision/tests/test_manager.py` + `test_resumer.py`：**13 passed**
- 全量：**177 passed**

---

## 5. 验收矩阵

| 能力 | 状态 | 证据与说明 |
|---|---|---|
| 多任务参数解析 | **PASS** | 四任务解析、去重、`--tasks`、非法参数；真实 preflight/batch-plan 均收到 4 个 task_id |
| 多任务依赖规划 | **PASS** | 开发计划 §13 依赖已落 `depends_on_tasks`；waves 3442→3443→3444→3445；循环/未知依赖 rc=1 |
| 多任务实际派发 | **PARTIAL** | 3442 有真实派发证据（4 节点 DONE、1 节点 RUNNING）；3443–3445 按约束未派发（避免重启进行中任务） |
| 多任务并行执行 | **PARTIAL** | 任务内并行已实证（3442 B1/B2 同时派发）；跨任务并行未执行，当前依赖链 + 文件耦合不适合并行 |
| 多任务异常恢复 | **PASS** | 隔离测试覆盖失败、WAITING_HUMAN、决策恢复、中断恢复、幂等、门禁 |
| 多任务最终验收 | **PARTIAL** | 任务级 gate 正确阻断 3442 结束；尚无已完成的多任务批次可做最终验收，未实现聚合 `batch-gate` |

---

## 6. 结论

### 6.1 当前多任务能力成熟度

- **规划与接入层：可用**。参数解析、预检、只读 batch-plan、依赖波次、幂等、运行中任务保护均已实证。
- **真实派发层：部分验证**。仅 3442 有历史真实派发；本轮没有新建多任务派发。
- **跨任务并行：未就绪**。当前四任务存在文件耦合，串行为正确策略。
- 综合：**可受控串行接入（约 70%）**，不建议宣称"多任务并行调度完成"。

### 6.2 是否可以正式投入使用

- **可以**用于：多任务参数接收、统一预检、只读计划与波次展示、运行中任务保护。
- **暂不可以**用于：不经设计确认就自动派发 3443–3445；跨任务并行执行。
- 3443–3445 进入实际执行前，必须先完成 A1/A2/A3（需求/设计/人工确认），再逐任务派发。

### 6.3 仍存在的风险

1. 3443–3445 的 DAG 是规划骨架，`files_owned` 未由 A2 细化，直接派发可能产生文件冲突。
2. 依赖来自开发计划文本，未写入 3442 的 DAG（未修改运行中任务文件）；后续需在 3443–3445 侧保持。
3. 无聚合 `batch-gate`：整体完成依赖逐任务 gate，主控需自行汇总。
4. `batch-plan` 对无 execution 的任务调用 `dispatch gate/plan` 仍可能创建空壳 execution（既有 K6），接入前应避免。
5. 全局安装 Skill 未更新，slash 入口仍为旧文档；需授权后 `scripts/install.sh`。
6. 跨任务并行未验证；若未来启用，必须先用独立任务验证文件隔离。

### 6.4 是否需要开发实际并行执行能力

**当前不需要**。这四个任务按开发计划是串行/半串行关系，并行收益低且冲突风险高。
只有当出现**无文件交集的独立任务批次**时，再在现有 `dispatch.py` 之上增加受控并行执行器；不要现在为抽象而建。

### 6.5 是否具备进入发布阶段的条件

- **源码与测试：具备**（177 passed，真实只读接入验证通过）。
- **正式发布：条件部分满足**。建议以 `READY_WITH_LIMITATIONS` 发布，披露：
  - 多任务仅验证到规划/接入层；
  - 3443–3445 未真实派发；
  - 跨任务并行未启用；
  - 全局 Skill 未安装。
- 发布前建议补：①三维任务完成设计确认后的真实接入；②聚合 `batch-gate`（可选）；③安装同步。

---

## 7. 本轮未做

- 未派发 3443/3444/3445 任何 Agent；未创建其 execution 记录。
- 未修改 3442 的 DAG、run-state、SQLite 状态；未中断 B2。
- 未提交 Git、未打 Tag、未安装全局 Skill、未触发 Jenkins。
