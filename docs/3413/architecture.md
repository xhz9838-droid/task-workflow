# 禅道 #3413 — 架构设计

## 1. 核心判断

**本次改动范围：仅 Web 端前端，2 个文件。后端、数据库、权限体系全部复用已有实现。**

依据：
- 审批端点 `POST /payrollBatch/{batchId}/approve` 已存在且完整实现（含状态校验、权限获取、wflow 同步、审批记录写入）
- 汇总端点 `GET /payrollBatch/{batchId}/summary` 已存在，返回 `PayrollSummaryDTO` 15+ 字段
- 权限码 `san_payroll_approve` 已存在于 sys_menu，已分配给 PROJECT_MANAGER 角色
- 移动端审批页（`payroll-approve/index.vue`）已完整实现审批 UI 和流程

## 2. 架构图

```
┌─────────────────────────────────────────────────────────┐
│ jeebootx-ui (Web 前端)                                    │
│                                                           │
│ Batch/index.vue     ───────→  审批汇总弹框（内联）          │
│ 操作列新增:                      │                        │
│  [审批] 按钮                     │ el-descriptions 15字段  │
│  v-auth=                        │ + [审批通过] [取消]       │
│  san_payroll_approve            │                        │
│       │                          │                        │
│       │ 点击                      │ 确认审批                │
│       ▼                          ▼                        │
│  GET /payrollBatch/{id}/summary  POST /payrollBatch/{id}/approve
└───────────────────────┬──────────────────────────────────┘
                        │ HTTP (网关 StripPrefix=1 剥 /sanitation)
                        ▼
┌─────────────────────────────────────────────────────────┐
│ jeebootx-sanitation (后端，已有，不改)                     │
│                                                           │
│ SanitationPayrollBatchController                          │
│   getSummary(batchId)  →  PayrollSummaryDTO               │
│   approve(batchId, taskId)                                │
│       │                                                   │
│       ▼                                                   │
│ SanitationPayrollBatchServiceImpl                         │
│   - 状态校验（必须 PENDING_APPROVAL）                       │
│   - approverId = SecurityUtils.getUser().getId()          │
│   - 写入 batch.status=APPROVED, approverId, approveTime   │
│   - completeExternalTask(agree) → wflow 待办完成           │
│       │                                                   │
│       ▼                                                   │
│ sanitation_payroll_batch 表                                │
└─────────────────────────────────────────────────────────┘
```

## 3. 技术决策

| 决策 | 方案 | 理由 |
|---|---|---|
| 弹框组件 | `el-dialog` + `el-descriptions` | 与 Flow/Step2 已有汇总弹框一致 |
| 汇总字段来源 | `PayrollSummaryDTO`（13+ 字段，以移动端 source `summaryRows` 为准） | 移动端是需求基准（"对齐移动端汇总字段"） |
| taskId 处理 | Web 端不传 taskId（`required=false`），仅完成本地审批状态变更 | wflow 待办由流程引擎超时或项目经理手动处理 |
| 审批确认 | `ElMessageBox.confirm` 二次确认 | 与 Approve/index.vue 现有模式一致 |
| 权限控制 | 前端 `v-auth="'san_payroll_approve'"` | 后端从 SecurityUtils 获取 approverId，天然防越权 |
| 状态按钮显隐 | `status === '已提交'` + `v-auth` | 与移动端 `canAudit = status === 'PENDING_APPROVAL'` 等价 |

## 4. 数据流

```
用户打开月份批次列表
  → GET /payrollBatch/page?status=&page=1&size=20
  → 表格渲染，status === '已提交' 的行显示 [审批] 按钮（条件：v-auth 通过）
  
用户点击 [审批]
  → GET /payrollBatch/{batchId}/summary
  → 弹框打开，el-descriptions 展示 13 字段汇总
  → 底部 [审批通过] [取消]

用户点击 [审批通过]
  → ElMessageBox.confirm('确认审批通过？')
  → POST /payrollBatch/{batchId}/approve
  → 成功：关闭弹框，ElMessage.success，刷新列表
  → 失败：ElMessage.error，弹框保持打开
```

## 5. 移动端字段对齐（规范来源）

以移动端 **source** (`payroll-approve/index.vue:102-122` 的 `summaryRows`) 为基准（`subtotal` 行已注释，Web 端同样不展示）：

| # | 标签 | 字段 | 格式 |
|---|---|---|---|
| 1 | 月份 | month | 文本 |
| 2 | 人数 | headcount | `{n} 人` |
| 3 | 综合工资 | totalSalary | ¥#,##0.00 |
| 4 | 缺勤工资 | totalAbsent | ¥#,##0.00 |
| 5 | 临时加班 | totalOvertime | ¥#,##0.00 |
| 6 | 顶岗/岗位补贴 | totalSubsidy | ¥#,##0.00 |
| 7 | 节假日补贴 | totalHoliday | ¥#,##0.00 |
| 8 | 处罚 | totalPenalty | ¥#,##0.00 |
| 9 | 奖励 | totalBonus | ¥#,##0.00 |
| 10 | 高温补贴 | totalHeat | ¥#,##0.00 |
| 11 | 其他补款 | totalOtherAdd | ¥#,##0.00 |
| 12 | 合计（应发） | totalPayable | ¥#,##0.00 |
| 13 | 实发工资 | totalNet | ¥#,##0.00（缺失时展示 0） |

注意：
- 不使用 dist-only `packageSalary` 的分组布局和字段名（源码已不存在）
- 不使用上个月对比（source 接口无 `lastMonth*` 字段）
- `fmtMoney`：JavaScript `toFixed(2)` + 正则千分位 + `¥` 前缀

## 6. 无需变更

- ❌ 无需新增数据库迁移脚本
- ❌ 无需修改 Java 代码
- ❌ 无需新增权限码
- ❌ 无需修改 OpenAPI 契约
- ❌ 无需修改移动端代码
- ❌ 无需修改 jeebootx (upms) 仓库