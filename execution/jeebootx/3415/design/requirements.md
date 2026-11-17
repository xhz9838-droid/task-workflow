# 需求分析 — 【测试】打卡配置列表新增字段是否启用围栏

> task_id: 3415 | project_key: jeebootx | 阶段: T02 需求分析（A1）
> 需求线索来源：任务标题 + 禅道变更历史（desc 未提供，见 task-context.md:26-35）。
> 证据标注格式 `仓库/文件:行号`；无代码证据的推断一律标 **推测**；desc 缺失导致的不确定性列「待确认问题」，不擅自加需求。

## 1. 任务背景与范围

| 项 | 内容 | 证据 |
|---|---|---|
| 任务名 | 【测试】打卡配置列表新增字段是否启用围栏 | task-context.md:11 |
| 标题变更 | 2026-11-17 由「新增字段显示」改为「新增字段是否启用围栏」，字段语义以「是否启用围栏」为准 | task-context.md:31-34 |
| desc | 未提供 | task-context.md:26 |
| 性质 | 本人自建自测的工作流验证任务（创建人=指派人） | task-context.md:35 |
| 范围结论 | **最小改动 = 打卡配置列表页新增一列展示现有字段 `fenceRequired`**。数据库、后端实体、列表接口响应均已存在该字段，无 DDL、无 API 契约变更（见 §4/§5） | 见 §4 现状盘点 |

## 2. 业务功能

### 2.1 功能定位

「打卡配置」= 环卫打卡规则（`sanitation_clock_rule`），PC 端配置页面为：

- 路由入口：`jeebootx-ui/src/views/sanitation/Config/RuleConfig/index.vue:18` — tab `workStandard` 标签「打卡配置」，组件指向 `../WorkStandard/index.vue`
- 列表页本体：`jeebootx-ui/src/views/sanitation/Config/WorkStandard/index.vue`（下称 WorkStandard 页）
- 列表数据接口：`GET /sanitation/clock-rule/page`（`jeebootx-ui/src/api/sanitation/clockRule.ts:5-16` → `SanitationClockRuleController.page`，`jeebootx-sanitation/.../controller/SanitationClockRuleController.java:71-75`）

### 2.2 FR-1（本次需求）：列表新增「是否启用围栏」列

- **作为**环卫运营管理员，**我希望在**打卡配置列表中**看到**每条打卡配置的「是否启用围栏」状态，**以便**不进编辑弹窗即可确认该班次规则是否做围栏校验。
- 现状缺口：WorkStandard 列表表格当前仅有「所属项目 / 打卡名称 / 目标角色 / 打卡频次 / 操作」五列（`WorkStandard/index.vue:36-73`），**无围栏相关列**（全文件检索 `围栏|fence` 无表格列命中）。
- 数据无需新增：行数据已携带 `fenceRequired`（接口响应含该字段，前端归一化时 `...r` 透传，`WorkStandard/index.vue:457-464`；TS 类型 `ClockRule.fenceRequired?: string`，`jeebootx-ui/src/api/sanitation/types.ts:154`）。
- 展示口径（与后端判定口径一致）：`fenceRequired === '0'` → 「不启用」；其余（`'1'`、null、脏值）→ 「启用」。依据后端消费语义：值为 `"0"` 时不校验围栏，其余（含 null/脏值）默认校验（`jeebootx-sanitation/.../service/impl/SanitationClockRecordServiceImpl.java:936-955`，`isFenceRequired`）。
- 列头文案采用任务标题用词「是否启用围栏」（字段语义以标题变更为证据，task-context.md:31-34）。

### 2.3 FR-2（待确认，不计入本次范围）：新增/编辑弹窗开放围栏开关

- 现状：WorkStandard 弹窗表单（打卡名称/所属项目/目标角色/打卡频次）**没有**围栏开关，提交时硬编码 `fenceRequired: '1'`（`WorkStandard/index.vue:388-404`，esp. :396）。
- 含义：若不开放开关，自建规则恒为「启用」，FR-1 列对自建规则永远显示「启用」（仅历史/手工改库数据可能为「不启用」）。
- 后端已支持传值：`ClockRuleSaveDTO.fenceRequired`（`jeebootx-sanitation-api/.../dto/ClockRuleSaveDTO.java:40-41`），保存/修改均落库（`SanitationClockRuleServiceImpl.java:107,142`）。
- 标题字面范围是「列表新增字段」；弹窗开放开关属新增交互，**不擅自实施**，列 §7 待确认问题 Q1（L3，人工决策）。

## 3. 业务流程与角色权限

### 3.1 涉及流程（均为既有流程，无流程改动）

1. 配置流程：管理员进入「规则配置 → 打卡配置」tab → 列表分页浏览 → 新增/编辑/删除打卡配置（`WorkStandard/index.vue:23,68-73`）。
2. 消费流程（本次不改动，仅语义参考）：移动端提交打卡 → 后端按规则 `fenceRequired` 决定是否围栏校验（`SanitationClockRecordServiceImpl.java:249-256,1033-1041`）。

### 3.2 角色权限（沿用现有，不新增权限点）

| 动作 | 权限标识 | 证据 |
|---|---|---|
| 查看列表 | `san_clock_rule_view`（刷新按钮 refresh-auth） | `WorkStandard/index.vue:24` |
| 新增/编辑/删除 | `san_clock_rule_update`（v-auth） | `WorkStandard/index.vue:23,70-71,147` |
| 数据范围 | 项目权限隔离：非超管仅本项目；列表排除系统内置规则（system_flag='1'） | `SanitationClockRuleServiceImpl.java:196-201` |

FR-1 为纯展示列，随列表权限天然可见，无需新权限点、无需改权限数据。

## 4. 数据实体与 API 现状盘点（复用分析）

| 层 | 现状 | 证据 | 本次是否改动 |
|---|---|---|---|
| 表 | `sanitation_clock_rule.fence_required char(1) DEFAULT '1' COMMENT '是否校验围栏'`，建表起即存在 | `jeebootx-sanitation/db/jeebootx_sanitation.sql:206`（另见 `db/ddlv0912.sql:169`） | 否（无需 DDL） |
| 实体 | `SanitationClockRuleEntity.fenceRequired`（注释「是否校验围栏」） | `SanitationClockRuleEntity.java:63-67` | 否 |
| 列表响应 VO | `ClockRuleVO.fenceRequired`（注释「是否需要围栏 0/1」），分页映射已填充 | `ClockRuleVO.java:47-48`；`SanitationClockRuleServiceImpl.java:865`（`toClockRuleVOWithoutSlots`） | 否 |
| 保存 DTO | `ClockRuleSaveDTO.fenceRequired` | `ClockRuleSaveDTO.java:40-41` | 否 |
| 列表接口 | `GET /clock-rule/page` → `R<IPage<ClockRuleVO>>`，响应已含 `fenceRequired` | `SanitationClockRuleController.java:71-75`；`SanitationClockRuleServiceImpl.java:182-205` | 否（契约不变） |
| 前端类型 | `ClockRule.fenceRequired?: string` | `types.ts:154` | 否 |
| 前端列表列 | 无围栏列 | `WorkStandard/index.vue:36-73` | **是（FR-1 唯一改动点）** |
| 前端弹窗 | 硬编码 `fenceRequired: '1'`，无开关 | `WorkStandard/index.vue:396` | 待确认（FR-2/Q1） |
| 业务消费 | 打卡提交按 `fenceRequired` 决定围栏校验（"0" 关闭，其余默认校验） | `SanitationClockRecordServiceImpl.java:936-955` | 否 |

结论：**优先复用**现有字段/接口/判定口径，全链路已通，唯缺列表展示列。

## 5. API（本次契约不变）

- 涉及接口：`GET /sanitation/clock-rule/page`（响应结构见 `design/openapi.yaml`）。
- **契约不变**：`ClockRuleVO` 自始含 `fenceRequired`（`ClockRuleVO.java:47-48`），本次不新增/不修改任何接口字段，仅前端消费已有字段。无 L3 契约变更。

## 6. 页面（本次改动点）

| 页面 | 文件 | 改动 |
|---|---|---|
| 规则配置-打卡配置列表 | `jeebootx-ui/src/views/sanitation/Config/WorkStandard/index.vue` | 表格新增「是否启用围栏」列（FR-1）；列宽预算需重排（该文件 :29-35 有列宽预算注释，约 1400px 可用宽度，现五列 min-width 合计 1170px） |

移动端（jeebootx-app）**不受影响**：端侧围栏软提示只用「作业网格多边形 + 全局容差配置」，不读规则级 `fenceRequired`（`jeebootx-app/src/packageClock/composables/useLocStatus.ts:131-134`；容差来源 `/clock-rule/fence-config`，`SanitationClockRuleController.java:139-143`）；规则级开关仅在后端打卡提交时消费（§4）。故本次无需改 app 端。（**推测**标注：app 端无「打卡配置列表」管理页 — 以 `jeebootx-app/src` 检索「打卡配置」仅命中后端语义注释为据。）

## 7. 约束、异常场景与待确认问题

### 7.1 约束

- C-1 不改 DDL、不改 API 契约（字段已存在，§4）。
- C-2 列表列展示口径必须与后端 `isFenceRequired` 一致（"0"→不启用，其余→启用），避免列表与打卡行为认知不一致（`SanitationClockRecordServiceImpl.java:936-955`）。
- C-3 列宽预算约束：WorkStandard 表格有明确宽度预算注释（`WorkStandard/index.vue:29-35`），新增列不得导致现有列（尤其目标角色 600px tag 折叠列）被挤压截断。
- C-4 权限/数据范围/系统内置规则过滤行为不变（§3.2）。

### 7.2 异常场景

| 场景 | 预期 | 依据 |
|---|---|---|
| `fenceRequired` 为 null / 脏值（历史数据） | 显示「启用」 | 与后端默认校验口径一致（`SanitationClockRecordServiceImpl.java:938-940`） |
| 接口未返回该字段（防御） | 按「启用」显示，不报错 | 口径同上；前端字段可选 `fenceRequired?: string`（types.ts:154） |
| 项目/角色名缺失 | 现有「—」占位行为不变 | `WorkStandard/index.vue:37-40,44-45` |

### 7.3 待确认问题（L3，不擅自决定）

| # | 问题 | 影响 | 建议 |
|---|---|---|---|
| Q1 | 新增/编辑弹窗是否开放「是否启用围栏」开关？（现硬编码 `'1'`，`WorkStandard/index.vue:396`） | 若不开放，FR-1 列对所有自建规则恒显「启用」，字段仅展示不可配置 | 本次仅做列表列（标题字面范围）；弹窗开关作为 FR-2 由人工决策后另行实施（后端无需改动即可支持） |
| Q2 | 列头/展示文案定稿：「是否启用围栏」+「启用/不启用」tag 是否符合预期？（后端注释为「是否校验围栏」） | 纯文案 | 默认按任务标题用词实施，可低成本调整 |

## 8. 验收标准（详细用例见 acceptance/acceptance-matrix.md）

- AS-1：打卡配置列表出现「是否启用围栏」列；`fence_required='1'` 的行显示「启用」。
- AS-2：`fence_required='0'` 的行显示「不启用」（可用 SQL 造数或调 PUT 接口构造）。
- AS-3：`fence_required` 为 null/脏值的行显示「启用」（与后端判定口径一致）。
- AS-4：新增列后表格不破版：目标角色列 tag 折叠展示正常，无表头截断（对照 `WorkStandard/index.vue:29-35` 宽度预算）。
- AS-5：回归：筛选/分页/新增/编辑/删除行为不变，权限标识不变。
- AS-6（仅当 Q1 确认实施 FR-2 时）：弹窗可切换围栏开关，保存后列表列随之变化，`fence_required='0'` 规则打卡时不校验围栏（后端既有行为）。
