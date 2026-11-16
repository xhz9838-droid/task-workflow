# 禅道 #3413 — 需求规格

## 1. 业务背景

薪酬管理此前仅支持项目经理在移动端审批月度薪酬批次。现需在 Web 端「薪酬管理-月份批次」页面增加审批入口：HR 提交批次后，项目经理可在批次列表中直接审批，无需跳转到独立的审批页或移动端。

## 2. 功能需求

### FR1：批次列表审批按钮

- **触发条件**：批次状态为「已提交」（PENDING_APPROVAL），且当前用户拥有 `san_payroll_approve` 权限
- **位置**：月份批次列表页（`Batch/index.vue`）操作列，「已提交」状态行
- **行为**：在现有「详情」「撤回审批」按钮旁新增「审批」按钮
- **权限**：`v-auth="'san_payroll_approve'"`（已有权限码，分配给 PROJECT_MANAGER 角色）

### FR2：薪酬汇总弹框

- **触发**：点击「审批」按钮
- **内容**：调用 `GET /payrollBatch/{batchId}/summary` 获取薪酬汇总数据
- **展示字段**（对齐移动端 PayrollSummaryDTO，共 15 字段）：

| # | 标签 | 字段 | 格式 |
|---|---|---|---|
| 1 | 薪酬月份 | month | YYYY-MM |
| 2 | 人数 | headcount | 整数 |
| 3 | 综合工资合计 | totalSalary | 金额（元，2 位小数） |
| 4 | 缺勤工资合计 | totalAbsent | 金额 |
| 5 | 临时加班合计 | totalOvertime | 金额 |
| 6 | 顶岗/岗位补贴合计 | totalSubsidy | 金额 |
| 7 | 小计 | subtotal | 金额 |
| 8 | 节假日补贴合计 | totalHoliday | 金额 |
| 9 | 处罚合计 | totalPenalty | 金额（扣减项） |
| 10 | 奖励合计 | totalBonus | 金额 |
| 11 | 高温补贴合计 | totalHeat | 金额 |
| 12 | 其他补款合计 | totalOtherAdd | 金额 |
| 13 | 合计（应发） | totalPayable | 金额 |
| 14 | 实发工资合计 | totalNet | 金额 |
| -- | 社保合计、公积金合计、个税合计 | totalSocial / totalFund / totalTax | 金额（如接口返回则展示） |

- 展示方式：el-descriptions 多列布局（复用 Flow/Step2 已有汇总弹框样式）
- 加载状态：展示 loading，接口失败时展示错误提示

### FR3：审批确认

- **弹框底部按钮**：「审批通过」(primary) + 「取消」
- **审批通过**：
  1. 二次确认（ElMessageBox.confirm）
  2. 调用 `POST /payrollBatch/{batchId}/approve?taskId=`（taskId 可为空——当前后端 `required = false`）
  3. 成功后：关闭弹框、刷新列表、ElMessage 成功提示
  4. 失败时：展示错误信息，弹框不关闭
- **取消**：关闭弹框

### FR4：wflow 待办消除

- 现状：`approve` 端点 `taskId` 参数可选。若不传 taskId，wflow 中的项目经理待办不会自动消除。
- **实现决定**：Web 端评审通过后，同步调用 wflow 完成待办（需要 taskId）。taskId 获取方式：后端 `approve` 方法内部根据 batch 的 `processInstanceId` 查询当前用户的待办 taskId。（注意：需要确认 wflow RemoteFlowService 是否提供查询待办的接口。如不支持，可保持 taskId 为空，wflow 待办由项目经理手动处理或后续补充。）

## 3. 非功能需求

### NFR1：权限
- 审批按钮仅对拥有 `san_payroll_approve` 权限的用户可见
- 后端 `approve` 方法从 SecurityUtils 获取当前用户 ID 作为 approverId，天然防止越权

### NFR2：状态一致性
- 审批前检查批次状态为 PENDING_APPROVAL（后端已有校验：`PayrollBatchStatusEnum.PENDING_APPROVAL`）
- 重复审批幂等：后端 `approve` 检查状态非 PENDING_APPROVAL 时抛异常

### NFR3：审计
- 审批人、审批时间写入 `sanitation_payroll_batch` 表（approverId/approveTime，已有字段）
- wflow 流程实例记录完整审批链路

### NFR4：兼容性
- 不改变移动端审批逻辑
- 不改变现有 API 契约
- 不影响现有「已提交」状态的其他操作（撤回审批、详情查看）

## 4. 不涉及的范围

- ❌ 不支持驳回（薪酬审批流程设计决定：无驳回，有疑问线下沟通）
- ❌ 不修改后端 Java 代码（端点已就绪）
- ❌ 不新增数据库表/字段
- ❌ 不新增权限码
- ❌ 不修改移动端代码
- ❌ 不新增审批历史功能

## 5. 验收用例

| # | 场景 | 前置条件 | 操作 | 预期结果 |
|---|---|---|---|---|
| AC1 | 项目经理看到审批按钮 | 批次状态=已提交，用户有 san_payroll_approve 权限 | 打开月份批次列表 | 「已提交」行操作列显示「审批」按钮 |
| AC2 | HR 看不到审批按钮 | 批次状态=已提交，用户有 san_payroll_submit 权限但无 san_payroll_approve | 打开月份批次列表 | 操作列不显示「审批」按钮 |
| AC3 | 未提交状态无审批按钮 | 批次状态=未提交 | 打开月份批次列表 | 操作列不显示「审批」按钮 |
| AC4 | 点击审批弹出汇总弹框 | 批次状态=已提交 | 点击「审批」按钮 | 弹框展示 15 字段薪酬汇总，loading → 数据展示 |
| AC5 | 审批通过 | 弹框已打开 | 点击「审批通过」→ 确认 | 弹框关闭、列表刷新、状态变为「已审批」 |
| AC6 | 取消审批 | 弹框已打开 | 点击「取消」 | 弹框关闭、列表不变 |
| AC7 | 重复审批 | 批次已被审批 | 点击「审批」（如有） | 后端返回错误（状态非 PENDING_APPROVAL），前端提示 |
| AC8 | 汇总接口异常 | 网络/服务异常 | 点击「审批」 | 弹框展示错误提示，不展示空白汇总 |