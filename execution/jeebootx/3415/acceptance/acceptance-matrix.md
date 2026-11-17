# 验收矩阵 — 任务 3415【测试】打卡配置列表新增字段是否启用围栏

> 阶段：实现期（A3 已确认 2026-11-17，B2 待实施）。本矩阵定义可执行验收用例；实现完成后由 QA（C1）执行并回填结果。
> 当前执行状态：**not_run**（B2 尚未实施，未运行任何测试）。
> 每条用例含：前置、步骤、预期、证据来源（代码位置或接口）。
> A3 决策：FR-2 取消（BLK-3415-01=不开放弹窗开关）→ AC-6/AC-7 取消；文案=「是否启用围栏」列头 + el-tag success(启用)/info(不启用)（BLK-3415-02）。

## 1. 需求 ↔ 用例对照

| 需求 ID | 需求（requirements.md） | 用例 | 优先级 | 状态 |
|---|---|---|---|---|
| FR-1 | 列表新增「是否启用围栏」列 | AC-1, AC-2, AC-3, AC-4 | P0 | not_run |
| NFR-1 | 展示口径与后端判定一致 | AC-3, AC-2 | P0 | not_run |
| NFR-2 | 权限/回归不变 | AC-5 | P0 | not_run |
| ~~FR-2~~ | ~~弹窗开放围栏开关~~ | ~~AC-6, AC-7~~ | — | **取消**（A3 BLK-3415-01 决策不实施） |

## 2. 验收用例

### AC-1 列存在且「启用」行展示正确
- **需求**：FR-1 / AS-1
- **前置**：存在 `fence_required='1'` 的自建打卡配置（现网/测试库默认数据即满足，弹窗硬编码 '1'，`WorkStandard/index.vue:396`）
- **步骤**：PC 登录（有 `san_clock_rule_view` 权限）→ 规则配置 → 打卡配置 tab → 查看列表
- **预期**：表格出现「是否启用围栏」列；`fence_required='1'` 行显示「启用」；列头完整不截断
- **证据来源**：页面 `jeebootx-ui/src/views/sanitation/Config/WorkStandard/index.vue`；数据 `GET /sanitation/clock-rule/page` 响应 `data.records[].fenceRequired`（`ClockRuleVO.java:47-48`）

### AC-2 「不启用」行展示正确
- **需求**：FR-1 / AS-2
- **前置**：构造 `fence_required='0'` 数据 —— 方式一（推荐）：`UPDATE sanitation_clock_rule SET fence_required='0' WHERE id=<测试规则ID>;`（测试库）；方式二：若 Q1 确认并实施 FR-2，经弹窗设置；方式三：调 `PUT /sanitation/clock-rule/{id}`（body 带 `fenceRequired:'0'`，契约已支持，`ClockRuleSaveDTO.java:40-41`）
- **步骤**：刷新打卡配置列表
- **预期**：该行「是否启用围栏」显示「不启用」
- **证据来源**：同 AC-1；口径依据 `SanitationClockRecordServiceImpl.java:955`（`"0"` 关闭校验）

### AC-3 缺省/脏值口径与后端一致
- **需求**：FR-1 / AS-3、NFR-1
- **前置**：构造 `fence_required IS NULL`（或任意非 '0' 字符）的测试数据
- **步骤**：刷新列表
- **预期**：显示「启用」（而非空白/「—」/报错）
- **证据来源**：后端缺省语义 `SanitationClockRecordServiceImpl.java:938-940`（null/脏值默认校验）

### AC-4 列宽预算不破版
- **需求**：FR-1 / AS-4、约束 C-3
- **前置**：存在目标角色超 3 个的规则（触发 tag 折叠 `+N`，`WorkStandard/index.vue:236-241`）；窗口宽约 1400px
- **步骤**：查看列表表格
- **预期**：无表头截断（对照历史问题「打卡频」截断，`WorkStandard/index.vue:29-35` 注释）；目标角色列 tag 折叠 + tooltip 正常；必要时出现横向滚动而非列挤压
- **证据来源**：`WorkStandard/index.vue:29-35`（宽度预算注释，实施后注释数字须同步更新）

### AC-5 回归：既有功能与权限不变
- **需求**：AS-5、NFR-2
- **步骤**：① 关键字/项目筛选与重置 ② 分页切页/改条数 ③ 新增一条打卡配置（含多时段）④ 编辑 ⑤ 删除 ⑥ 无 `san_clock_rule_update` 权限账号仅可见列表无操作按钮
- **预期**：全部行为与改动前一致；新增列不影响其他列数据；系统内置规则不出现在列表（`SanitationClockRuleServiceImpl.java:196-197`）
- **证据来源**：`WorkStandard/index.vue:186-208,406-448`；权限 `WorkStandard/index.vue:23-24,70-71,147`

### AC-6 ~~（FR-2，已取消）~~
- **状态**：**取消** — A3 BLK-3415-01 决策不实施 FR-2（弹窗开关）。原用例随 FR-2 取消，不再执行。

### AC-7 ~~（FR-2，已取消）~~
- **状态**：**取消** — 同 AC-6，随 FR-2 取消。

## 3. 证据来源汇总（设计期核对记录）

| 核对项 | 结论 | 位置 |
|---|---|---|
| DB 列已存在 | 无需 DDL | `jeebootx-sanitation/db/jeebootx_sanitation.sql:206` |
| 列表接口已返回字段 | 契约不变 | `ClockRuleVO.java:47-48`；`SanitationClockRuleServiceImpl.java:865` |
| 前端列表缺列 | FR-1 改动点 | `WorkStandard/index.vue:36-73`（无围栏列） |
| 前端类型已备 | 无需改 | `types.ts:154` |
| 弹窗硬编码 '1' | FR-2 取消，维持现状 | `WorkStandard/index.vue:396`（A3 决策不实施） |
| 移动端不受影响 | 无需改 app | `useLocStatus.ts:131-134` |

## 4. 执行记录（QA 回填区）

| 用例 | 执行结果 | 证据（截图/日志/commit） | 执行人 | 日期 |
|---|---|---|---|---|
| AC-1 | not_run | — | — | — |
| AC-2 | not_run | — | — | — |
| AC-3 | not_run | — | — | — |
| AC-4 | not_run | — | — | — |
| AC-5 | not_run | — | — | — |
| AC-6 | 取消（FR-2 不实施） | — | — | 2026-11-17 A3 |
| AC-7 | 取消（FR-2 不实施） | — | — | 2026-11-17 A3 |
