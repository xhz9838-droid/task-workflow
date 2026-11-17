# 数据字典 — 「是否启用围栏」字段（任务 3415）

> 结论：**无新增数据库字段**。列表新增列展示的是既有字段 `sanitation_clock_rule.fence_required`。
> 本字典记录该字段的规范定义、展示映射与口径证据，供实施/验收对照。

## 1. 字段定义（既有，复用）

| 项 | 值 | 证据 |
|---|---|---|
| 表 | `sanitation_clock_rule`（打卡规则表/打卡配置） | `SanitationClockRuleEntity.java:20`（@TableName） |
| 列名 | `fence_required` | `jeebootx-sanitation/db/jeebootx_sanitation.sql:206` |
| 类型 | `char(1)`，utf8mb4 | 同上 |
| 可空 | YES（NULL 允许） | 同上 |
| 默认值 | `'1'` | 同上 |
| 列注释 | 「是否校验围栏」 | 同上 |
| 实体字段 | `SanitationClockRuleEntity.fenceRequired: String` | `SanitationClockRuleEntity.java:63-67` |
| API 字段 | `ClockRuleVO.fenceRequired: String`（注释「是否需要围栏 0/1」） | `ClockRuleVO.java:47-48` |
| 前端类型 | `ClockRule.fenceRequired?: string` | `jeebootx-ui/src/api/sanitation/types.ts:154` |

## 2. 取值与语义

| 值 | 含义 | 打卡提交时行为 | 证据 |
|---|---|---|---|
| `'1'` | 启用围栏（校验围栏） | 定位需落在作业网格多边形内（含容差），否则记 `LOCATION_OUT_OF_RANGE` 标记 | `SanitationClockRecordServiceImpl.java:249-256`、`isFenceRequired` :955 |
| `'0'` | 不启用围栏 | 跳过围栏校验 | `SanitationClockRecordServiceImpl.java:936-955`（仅 `"0"` 返回 false） |
| `NULL` / 脏值 | 按「启用」兜底 | 默认校验（兼容历史数据） | `SanitationClockRecordServiceImpl.java:938-940`（注释明示） |

枚举形式取值（写入规范）：`0` / `1`（后端约定 `String` 型 char(1)，与 `system_flag` 等标记字段同范式；CLAUDE.md 约定布尔/标记字段用 `_flag` 后缀——本字段名为历史遗留 `fence_required`，**不改名**，改名属破坏性 DDL 且无收益）。

## 3. 前端展示映射（FR-1，本次实施）

| fenceRequired | 列「是否启用围栏」显示 | 说明 |
|---|---|---|
| `'0'` | 不启用 | 与后端 `isFenceRequired` 同口径 |
| 其他（`'1'`/null/脏值/字段缺失） | 启用 | 口径同 `SanitationClockRecordServiceImpl.java:938-940` |

列头文案「是否启用围栏」取自任务标题（task-context.md:31-34 变更历史）；字段注释「是否校验围栏」为同义，不做双文案。

## 4. 写入口径（现状，FR-2 确认前不变）

| 写入方 | 值 | 证据 |
|---|---|---|
| PC 新增/编辑弹窗 | 硬编码 `'1'` | `WorkStandard/index.vue:396`（buildSavePayload） |
| 系统默认班次（迁移预置） | `'1'` | `V20261112_001__clock_rule_system_and_project.sql:44-46` |
| 后端保存接口 | 透传 `ClockRuleSaveDTO.fenceRequired` | `SanitationClockRuleServiceImpl.java:107,142` |

## 5. 关联配置（非本字段，仅上下文）

| 项 | 说明 | 证据 |
|---|---|---|
| 围栏几何 | 作业网格 `boundary`（GeoJSON Polygon），打卡时按命中网格判定 | `SanitationClockRecordServiceImpl.java:251-256` |
| 围栏容差 | `sys_config` 键 `sanitation.clock.fence.tolerance-meters`，默认 0=严格包含 | `SanitationConstant.java:212-227`；`SanitationClockRuleController.java:139-143` |
