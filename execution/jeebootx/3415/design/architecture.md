# 技术设计 — 【测试】打卡配置列表新增字段是否启用围栏

> task_id: 3415 | 阶段: T03 技术设计（A2） | 前置: design/requirements.md（A1）
> 设计原则：最小改动、复用现有字段/接口/口径；DDL 与 OpenAPI 无变更；desc 未提供的部分不加需求（见 requirements.md §7.3）。

## 1. 结论概览

**本次唯一必做改动 = PC 前端 1 个文件加 1 个表格列**：

| 仓库 | 文件 | 改动 | 对应需求 |
|---|---|---|---|
| jeebootx-ui | `src/views/sanitation/Config/WorkStandard/index.vue` | `el-table` 新增「是否启用围栏」列 + 列宽预算微调 | FR-1 |
| （可选，待 Q1 确认） | 同上 | 新增/编辑弹窗加开关，替换 `buildSavePayload` 硬编码 `fenceRequired: '1'` | FR-2 |

不改：sanitation 后端、upms、jeebootx-app、任何 DDL、任何 API 契约（证据见 §2 复用分析与 §3）。

## 2. 改动点定位与复用分析

### 2.1 数据链路（全部现成，逐层证据）

```
sanitation_clock_rule.fence_required          -- DB 列，DEFAULT '1'
  jeebootx-sanitation/db/jeebootx_sanitation.sql:206
        │ MyBatis-Plus 映射
SanitationClockRuleEntity.fenceRequired        -- jeebootx-sanitation-biz/.../entity/SanitationClockRuleEntity.java:63-67
        │ toClockRuleVOWithoutSlots 填充
ClockRuleVO.fenceRequired                      -- jeebootx-sanitation-api/.../vo/ClockRuleVO.java:47-48
        │                                      -- 映射点 SanitationClockRuleServiceImpl.java:865
GET /sanitation/clock-rule/page → R<IPage<ClockRuleVO>>
        │                      -- SanitationClockRuleController.java:71-75
        │                      -- pageByScope SanitationClockRuleServiceImpl.java:182-205
前端 getClockRulePage → rows（...r 透传 fenceRequired）
        │              -- api/sanitation/clockRule.ts:5-16
        │              -- WorkStandard/index.vue:457-464
WorkStandard 表格 ← 当前无该列（缺口）           -- WorkStandard/index.vue:36-73
```

### 2.2 前端改动设计（FR-1）

文件：`jeebootx-ui/src/views/sanitation/Config/WorkStandard/index.vue`

1. 新增表格列（放在「打卡频次」与「操作」之间）：
   - `label="是否启用围栏"`（文案取自任务标题，requirements.md §7.3 Q2），`min-width="110"`（表头 6 个全角字符 ≈84px + 单元格内边距）。
   - 单元格模板：`row.fenceRequired === '0'` → 「不启用」（可配 `el-tag type="info"`），否则 → 「启用」（`el-tag type="success"` 或纯文本，实施时与同表「—」占位风格协调）。
   - **口径必须与后端 `isFenceRequired` 一致**：只有显式 `"0"` 算不启用，null/脏值/"1" 均算启用 — 依据 `SanitationClockRecordServiceImpl.java:936-955`（含 :938-940 缺省语义注释）。
2. 列宽预算重排：该文件 :29-35 有明确宽度预算注释（可用宽约 1400px，现列 min-width 合计 160+120+600+120+170=1170px）。新增 110px 后合计 1280px 仍在预算内；若实测溢出，从「目标角色」600px 向下压（tag 折叠 `VISIBLE_ROLE_MAX=3` 已存在，:236-241），但保持 ≥ 500px 以免 tooltip 折叠体验劣化。实施后更新该注释中的数字（注释即文档，勿留过期数字）。
3. 无 TS 类型改动：`ClockRule.fenceRequired?: string` 已存在（`api/sanitation/types.ts:154`）。
4. 无 API 封装改动：`getClockRulePage` 返回已含该字段（`api/sanitation/clockRule.ts:5-16`）。

### 2.3 可选改动（FR-2，待 Q1 确认后实施，后端零改动）

同文件弹窗表单加「是否启用围栏」`el-switch`（或 radio）：
- `standardForm` 增 `fenceRequired: '1' | '0'`；`resetStandardForm` 归 `'1'`（与 DB DEFAULT '1' 一致）；`openEdit` 回显 `row.fenceRequired`。
- `buildSavePayload`（`WorkStandard/index.vue:396`）由硬编码 `'1'` 改为传表单值。
- 后端无需任何改动：`ClockRuleSaveDTO.fenceRequired` 已接收并落库（`ClockRuleSaveDTO.java:40-41`；`SanitationClockRuleServiceImpl.java:107,142`）。

## 3. 兼容性说明

| 维度 | 结论 | 证据 |
|---|---|---|
| 数据库 | 无 DDL（列已存在，DEFAULT '1'） | `db/jeebootx_sanitation.sql:206` |
| API 契约 | 不变；`ClockRuleVO` 自始含 `fenceRequired` | `ClockRuleVO.java:47-48` |
| 后端行为 | 不变（`fenceRequired` 消费逻辑既有） | `SanitationClockRecordServiceImpl.java:936-955` |
| 历史数据 | null/脏值显示「启用」，与后端缺省校验一致，无数据迁移 | `SanitationClockRecordServiceImpl.java:938-940` |
| 移动端 | 不受影响：端侧围栏软提示用网格多边形+全局容差，不读规则级 `fenceRequired` | `useLocStatus.ts:131-134`；`SanitationClockRuleController.java:139-143` |
| 权限 | 沿用 `san_clock_rule_view`/`san_clock_rule_update`，不新增权限点 | `WorkStandard/index.vue:23-24,70-71` |
| 系统内置规则 | 列表本就过滤 system_flag='1'（`SanitationClockRuleServiceImpl.java:196-197`），无特殊处理 | 同左 |
| 回归面 | 纯增列，不触碰现有列/筛选/分页/弹窗逻辑（FR-2 确认前） | — |

## 4. 架构决策（ADR）

- **ADR-1 复用 `fence_required` 而非新增「是否启用围栏」字段**：标题「新增字段」指列表新增字段展示；DB/实体/VO 已有语义等价字段（「是否校验围栏」），新增第二字段会造成双源不一致。结论：复用。证据：§2.1。
- **ADR-2 展示口径对齐后端 `isFenceRequired`（仅 `"0"` 为不启用）**：列表是运营确认打卡行为的窗口，必须与打卡提交判定同口径。证据：`SanitationClockRecordServiceImpl.java:936-955`。
- **ADR-3 弹窗开关列为 FR-2 待确认（L3），本次不实施**：标题字面范围为「列表」；弹窗硬编码 `'1'` 的现状不破坏任何既有功能（新建规则默认启用围栏，与 DB DEFAULT 一致）。待人工决策（requirements.md §7.3 Q1）。

## 5. 影响文件清单（实施阶段交接）

| 文件 | 仓库 | 动作 | 优先级 |
|---|---|---|---|
| `src/views/sanitation/Config/WorkStandard/index.vue` | jeebootx-ui | Edit：表格加列 + 列宽预算注释更新 | P0（FR-1） |
| 同上 | jeebootx-ui | Edit：弹窗开关 + buildSavePayload 去硬编码 | P1（FR-2，Q1 确认后） |

无后端文件、无 DDL 文件、无契约文件需要动。
