# 禅道 #3413 — 环境与代码分析

> 调查方式：只读。无禅道写操作，无 Jenkins 触发，未修改任何业务仓库文件。

## 1. 禅道任务摘要

| 字段 | 值 |
|---|---|
| ID | #3413 |
| 名称 | 薪酬管理新增web端支持审批功能 |
| 状态 | wait |
| 优先级 | 3 |
| 迭代 | 智慧环卫202611 (ID 191) |
| 负责人 | xuhongzu（已核验归属） |
| 项目 | 181 |
| 关联需求 | 无 |
| 预估/已耗/剩余 | 均为 0.00 |
| 计划开始/截止 | 空 |
| 描述 | "薪酬管理之前都是项目经理在移动端审批，目前需要在web端薪酬管理-月份批次页面，新增hr提交后，项目经理有该月份的审批按钮 点击后出现薪酬汇总弹框以及审批确认按钮，弹框内容对齐移动端汇总字段。" |

## 2. 四仓库状态

| 仓库 | 分支 | 最新提交 | 未提交文件 |
|---|---|---|---|
| jeebootx-sanitation | dev | `7a8b8c3` (11-13) | 4 个 zentao_bug_* 文件（非代码） |
| jeebootx (upms/平台) | dev | `d72949b` (11-10) | 1 个 seata sessionStore |
| jeebootx-ui (Web) | dev | `2589aae` (11-12) | 无 |
| jeebootx-app (移动) | dev | `8289f98` (11-12) | `.env.development` |

key finding: Web Approval page already exists

## 3. 薪酬模块架构（后端）

### 3.1 状态机

```
DRAFT ──submit────→ PENDING_APPROVAL ──approve──→ APPROVED
  ↑                      │
  └──────withdraw────────┘
```

| 状态 | 枚举值 | 设置者 | 含义 |
|---|---|---|---|
| 未提交 | DRAFT | 项目人事（HR） | 新建批次后、可修改考勤/薪资 |
| 已提交 | PENDING_APPROVAL | 项目人事 submit | 等待项目经理审批 |
| 已审批 | APPROVED | 项目经理 approve | 归档锁定 |

- 路径：`PayrollBatchStatusEnum.java` (`jeebootx-sanitation-biz/.../enums/`)

### 3.2 关键实体

| 实体 | 表 | 关键字段 |
|---|---|---|
| SanitationPayrollBatchEntity | `sanitation_payroll_batch` | id, deptId, payrollMonth, status, submitterId, submitTime, approverId, approveTime, processInstanceId, 4 个合计字段 |
| SanitationPayrollItemEntity | `sanitation_payroll_item` | 60+ 字段：综合工资、各类补贴、加班、缺勤、社保、公积金、个税、应发、实发等 |

### 3.3 Controller / Service

| 层 | 类 |
|---|---|
| Controller | `SanitationPayrollBatchController` |
| Service | `SanitationPayrollBatchService` / `SanitationPayrollBatchServiceImpl` |
| Mapper | `SanitationPayrollBatchMapper` + XML |

### 3.4 已有审批相关端点

| 方法 | 路径 | 用途 | Controller 行号 |
|---|---|---|---|
| GET | `/payrollBatch/page` | 批次分页列表 | :65-71 |
| GET | `/payrollBatch/{batchId}/summary` | 薪酬汇总 | :137-142 |
| POST | `/payrollBatch/{batchId}/submit` | 提交审批 | :89-96 |
| POST | `/payrollBatch/{batchId}/withdraw` | 撤回审批 | :100-107 |
| POST | `/payrollBatch/{batchId}/approve?taskId=` | 审批通过 | :122-134 |

### 3.5 审批机制

- **双重机制**：自有 `status` 字段 + wflow 流程引擎（Feign 调用 `RemoteFlowService`，非 jeebootx-bpm 的 Flowable）
- 流程定义 key：`payroll_approval_flow`
- **不支持驳回**（源码注释："无驳回，有疑问线下沟通"）
- 无独立审批历史表（审批信息记录在 batch 表自身）
- `ProcessEventListener` 未注册 payroll 的回调（审批同步完成，不依赖异步回调）

### 3.6 权限

| 权限码 | 名称 | 角色 |
|---|---|---|
| `san_payroll_view` | 薪酬查看 | HR / PROJECT_HR / PROJECT_MANAGER |
| `san_payroll_submit` | 提交/撤回审批 | HR / PROJECT_HR |
| `san_payroll_approve` | 审批通过 | PROJECT_MANAGER |
| `san_payroll_step1_fix` | Step1 修正 | — |
| `san_payroll_step2_import` | Step2 导入 | — |

权限通过 v-auth 前端指令 + sys_menu 按钮权限码 + 后台角色分配实现。后端不做硬编码角色判断。

项目级隔离：`deptId` → `SanitationDeptFacade.resolveScopeDeptIds()` → 超管看全部，普通用户按 scopeDeptId 子树。

### Key Finding: Approve method signature

### 3.7 DDL / 迁移

- 初始建表：`db/二期/jeebootx_sanitation1021.sql`（行 920-996）
- Flyway 迁移：`db/migration/sanitation/V20261023_002__*` 至 `V20261104_002__*`（共 8 个）
- 权限 SQL：`db/migration/upms/V20261104_001__*`、`V20261106_001__*`

### 3.8 构建

- JDK 17（pom.xml；CLAUDE.md 写 21 但以 pom 为准）
- Spring Boot 3.5.5，Maven 多模块
- `mvn clean package -DskipTests`
- 现有测试：3 个（LeaveSlotCalculator、InsurancePersonMatcher、ClockMatchEngine），**无 Payroll 相关测试**

## 4. Web 端分析

### 4.1 月份批次页面

- 文件：`src/views/sanitation/Personnel/Salary/Batch/index.vue`
- 表格列：序号 | 月份（可点击进核算流程） | 总人数 | 综合工资合计 | 应发工资合计 | 实发工资合计 | 状态(el-tag) | 操作
- 操作按钮按状态：
  - 未提交：「进入计算」+「提交审批」(v-auth="san_payroll_submit")
  - 已提交：「详情」+「撤回审批」(v-auth="san_payroll_submit") — **无审批按钮**
  - 已审批：「详情」

### 4.2 已有审批页

- 文件：`src/views/sanitation/Personnel/Salary/Approve/index.vue`
- 通过 `?month=` query 进入，展示 StatCards + 明细表格
- 已提交状态：「审批通过」(v-auth="san_payroll_approve") +「撤回审批」
- 该页面通过 URL 参数定位，非从批次列表直接进入

### 4.3 现有汇总弹框

- 文件：`Flow/Step2/index.vue` 行 186-224
- el-dialog + el-descriptions 展示 15 字段工资汇总 + 确认提交
- **可直接复用为项目经理审批弹框的基础**

### 4.4 API 模块

- 文件：`src/api/sanitation/salary.ts`
- 已有 `approveSalaryBatch` 函数（POST `/sanitation/payrollBatch/{batchId}/approve`，行 119）
- 已有 `getSalarySummary` 函数（GET `/sanitation/payrollBatch/{batchId}/summary`，行 149）
- Batch/index.vue 当前未导入这两个函数

### 4.5 状态映射

```ts
// salary.ts :43-47
PENDING_APPROVAL → '已提交'
APPROVED → '已审批'
其他 → '未提交'
```

### 4.6 组件与模式

- Element Plus 2.5.5（el-dialog、el-table、el-tag、el-descriptions）
- 权限指令：`v-auth="'san_payroll_approve'"`
- 用户信息：`stores/userInfo`（pinia），权限列表 `authBtnList`
- 格式化：`fmtMoney`、`fmtMonth`（`utils/format.ts`）
- 无 vitest/jest/playwright（package.json 无 test 脚本）
- Node >= 16，pnpm，TypeScript 4.9.5，Vite 4.3.3

### 4.7 CLAUDE.md / AGENTS.md

- 仅含 ai-memory v1 模板，无项目特定约束

## 5. 移动端（等待 Agent 报告中）

移动端审批页路径：
`src/packageApproval/pages/payroll-approve/index.vue`

入口：首页消息待办，URL 带 `businessId/procInsId/taskId/status=todo`

调用的后端端点：
- `GET /sanitation/payrollBatch/{batchId}/summary`（汇总）
- `POST /sanitation/payrollBatch/{batchId}/approve?taskId=...`（审批通过）

### 5.1 汇总字段（移动端 TypeScript 接口，来自后端报告）

| 字段 | 中文 |
|---|---|
| month | 薪酬月份 |
| headcount | 人数 |
| totalSalary | 综合工资合计 |
| totalAbsent | 缺勤工资合计 |
| totalOvertime | 临时加班合计 |
| totalSubsidy | 顶岗/岗位补贴合计 |
| subtotal | 小计 |
| totalHoliday | 节假日补贴合计 |
| totalPenalty | 处罚合计 |
| totalBonus | 奖励合计 |
| totalHeat | 高温补贴合计 |
| totalOtherAdd | 其他补款合计 |
| totalPayable | 合计（应发） |
| totalNet | 实发工资合计 |
| batchId | 批次 ID |
| status | 批次状态 |

（完整 15+ 字段对齐以移动端 Agent 报告为准）

## 6. 关键发现

1. Web 审批页已存在但入口不直观：通过 URL `?month=` 进入，批次列表页的"已提交"行没有审批按钮。
2. 后端审批端点已完整实现：`POST /payrollBatch/{batchId}/approve?taskId=`（taskId 参数 `required=false`）。**#3413 主要是前端改动**。
3. 审批只支持"通过"，不支持驳回（设计决定，非遗漏）。
4. 汇总弹框已有：Step2 的提交审批弹框可直接复用样式和字段。
5. workflow taskId 获取：移动端从 wflow 消息待办 URL 获取；Web 端如从批次列表直接审批，taskId 可传空（但 wflow 待办不会自动消除 — 需确认这是否是可接受的业务行为）。
6. 无后端代码改动（审批接口已就绪），仅需前端增加批次列表页的审批按钮和弹框。