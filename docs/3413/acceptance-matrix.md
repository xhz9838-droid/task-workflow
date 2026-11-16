# 禅道 #3413 — 验收矩阵

## 验收项

| # | 验收项 | 验证方式 | 证据 | 状态 |
|---|---|---|---|---|
| AC1 | 项目经理可见审批按钮 | 人工/截图：指定项目经理账号登录，查看「已提交」状态批次的操作列 | 截图：操作列含"审批"按钮 | ⬜ 待验证 |
| AC2 | HR 不可见审批按钮 | 人工/截图：HR 账号登录，同一批次的操作列 | 截图：操作列无"审批"按钮 | ⬜ 待验证 |
| AC3 | 未提交/已审批无审批按钮 | 查看不同状态批次的操作列 | 截图/代码审查 | ⬜ 待验证 |
| AC4 | 点击审批弹出汇总弹框 | 点击审批按钮，弹框展示 13 字段，loading → 数据 | 截图：弹框含完整字段 | ⬜ 待验证 |
| AC5 | 汇总字段对齐移动端 | 逐字段对比 `PayrollSummaryDTO` 字段与弹框 el-descriptions-item label | 代码 diff / 对照表 | ⬜ 待验证 |
| AC6 | 审批通过 | 点击审批通过 → 确认 → 成功提示 → 列表刷新 → 状态变已审批 | 截图：操作前后对比 | ⬜ 待验证 |
| AC7 | 取消审批 | 点击取消 → 弹框关闭，列表不变 | 手动操作 | ⬜ 待验证 |
| AC8 | 汇总接口异常处理 | Mock 网络错误，点击审批按钮 | 弹框关闭 + 错误提示 | ⬜ 待验证 |
| AC9 | 审批接口异常处理 | Mock 网络错误，点击审批通过 | 弹框不关闭 + 错误提示 | ⬜ 待验证 |
| AC10 | 权限码 san_payroll_approve 使用正确 | 代码审查：v-auth 指令值 | grep src/views/ | ⬜ 待验证 |
| AC11 | 后端状态校验 | 已审批批次再次调用 approve | 后端返回 400 | ⬜ 待验证 |
| AC12 | approverId 正确写入 | 审批通过后查询 `sanitation_payroll_batch` 表 | SQL 查询 | ⬜ 待验证 |

## 13 字段对齐清单

| 移动端标签 | 移动端字段 | Web 端标签 | Web 端字段 | 一致 |
|---|---|---|---|---|
| 月份 | month | 月份 | month | ⬜ |
| 人数 | headcount | 人数 | headcount | ⬜ |
| 综合工资 | totalSalary | 综合工资 | totalSalary | ⬜ |
| 缺勤工资 | totalAbsent | 缺勤工资 | totalAbsent | ⬜ |
| 临时加班 | totalOvertime | 临时加班 | totalOvertime | ⬜ |
| 顶岗/岗位补贴 | totalSubsidy | 顶岗/岗位补贴 | totalSubsidy | ⬜ |
| 节假日补贴 | totalHoliday | 节假日补贴 | totalHoliday | ⬜ |
| 处罚 | totalPenalty | 处罚 | totalPenalty | ⬜ |
| 奖励 | totalBonus | 奖励 | totalBonus | ⬜ |
| 高温补贴 | totalHeat | 高温补贴 | totalHeat | ⬜ |
| 其他补款 | totalOtherAdd | 其他补款 | totalOtherAdd | ⬜ |
| 合计（应发） | totalPayable | 合计（应发） | totalPayable | ⬜ |
| 实发工资 | totalNet | 实发工资 | totalNet | ⬜ |

## 非功能验收

| # | 验收项 | 标准 | 状态 |
|---|---|---|---|
| NF1 | 无后端改动 | `git diff` jeebootx-sanitation 为空 | ⬜ |
| NF2 | 无数据库改动 | 无新增 Flyway 脚本 | ⬜ |
| NF3 | 无新增依赖 | package.json 不变 | ⬜ |
| NF4 | 无移动端改动 | `git diff` jeebootx-app 为空 | ⬜ |
| NF5 | 遵循项目代码规范 | 复用 fmtMoney、v-auth、el-dialog 模式 | ⬜ |
| NF6 | 审批操作幂等 | 重复审批不产生副作用 | ⬜ |

---

## 验收人签字

- [ ] QA Agent（qa-engineer）
- [ ] Integration Reviewer（integration-reviewer）
- [ ] Main Agent 复核
- [ ] **本人（xuhongzu）最终确认 → task_finish**