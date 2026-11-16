# 禅道 #3413 — 仓库映射与修改范围

## 1. 仓库角色

| 仓库 | 角色 | 本次修改 |
|---|---|---|
| `jeebootx-sanitation` | 环卫业务后端（薪酬模块在此） | **只读审查**（审批端点已就绪，无需后端改动） |
| `jeebootx`（upms） | 平台/权限/BPM | **不涉及**（权限码已存在，无需新增） |
| `jeebootx-ui` | Web 前端 | **主要修改**：批次列表页增加审批按钮 + 汇总弹框 |
| `jeebootx-app` | 移动端 | **只读审查**（确认汇总字段对齐参考） |

## 2. 需要修改的文件

### 2.1 jeebootx-ui（Web 前端）— 2 个文件

| 文件 | 改动 | 说明 |
|---|---|---|
| `src/views/sanitation/Personnel/Salary/Batch/index.vue` | 在"已提交"操作列新增审批按钮 | 增加 `v-auth="'san_payroll_approve'"` 的审批按钮，导入 `approveSalaryBatch` 和 `getSalarySummary` |
| `src/views/sanitation/Personnel/Salary/Batch/` （新增或内联） | 审批汇总弹框 | 可复用 Flow/Step2 的 el-descriptions 15 字段布局，或内联在 Batch 页 |

### 2.2 不涉及的文件（无需改动）

- 所有 Java 后端文件（Controller/Service/Mapper/Entity）：审批端点 `POST /payrollBatch/{batchId}/approve` 和汇总端点 `GET /payrollBatch/{batchId}/summary` 已存在，无需修改
- 权限 SQL：`san_payroll_approve` 权限码已存在（V20261104_001），无需新增
- 数据库 DDL/迁移：无需变更
- jeebootx-app（移动端）：无需改动

## 3. 文件所有权分配

| Agent | 文件 | 说明 |
|---|---|---|
| web-frontend | `jeebootx-ui/src/views/sanitation/Personnel/Salary/Batch/index.vue` | 审批按钮 + 汇总弹框 |
| web-frontend | `jeebootx-ui/src/api/sanitation/salary.ts` | 无需改（approveSalaryBatch/getSalarySummary 已存在），仅 import |
| architect | `docs/3413/*` | 设计文档 |

其余 Agent（database、java-backend、mobile-app）本次无修改任务，仅参与审查。

## 4. 后端端点确认

以下端点已存在，Web 端直接调用：

| 端点 | 方法 | 用途 | 参数 |
|---|---|---|---|
| `/payrollBatch/page` | GET | 批次列表 | page, size, status, deptId, month |
| `/payrollBatch/{batchId}/summary` | GET | 薪酬汇总 | batchId（路径） |
| `/payrollBatch/{batchId}/approve` | POST | 审批通过 | batchId（路径），taskId（query，可选） |

注意：`approve` 的 `taskId` 参数 `required = false`。如果 Web 端从批次列表直接发起审批（不走 wflow 待办中心），taskId 可为空，但 wflow 中的待办不会自动消除。这是业务需确认的点。

## 5. 汇总字段对齐

Web 端弹框必须对齐移动端 `PayrollSummaryDTO` 的以下字段（来源：`app/src/packageApproval/pages/payroll-approve/index.vue` 的 `summaryRows`）：

待移动端 Agent 报告确认具体字段顺序和标签文案。