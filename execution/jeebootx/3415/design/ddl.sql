-- ============================================================================
-- ddl.sql — 任务 3415【测试】打卡配置列表新增字段是否启用围栏
-- 结论：**无需 DDL**。复用既有列 sanitation_clock_rule.fence_required。
-- 本文件仅记录证据与核验 SQL，不执行任何变更。
-- ============================================================================

-- 证据 1：建表 DDL 已含该列（自 v0912 初始结构即存在）
--   来源：jeebootx-sanitation/db/jeebootx_sanitation.sql:206
--   来源：jeebootx-sanitation/db/ddlv0912.sql:169
--   定义：
--     `fence_required` char(1) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci
--       NULL DEFAULT '1' COMMENT '是否校验围栏'

-- 证据 2：迁移脚本以 fence_required 为锚点加列，证明该列早已存在
--   来源：jeebootx-sanitation/db/migration/sanitation/V20261112_001__clock_rule_system_and_project.sql:15
--     ... ADD COLUMN `system_flag` ... AFTER `fence_required`

-- 证据 3：实体与 VO 均映射该列，无需结构变更
--   SanitationClockRuleEntity.fenceRequired（SanitationClockRuleEntity.java:63-67）
--   ClockRuleVO.fenceRequired（ClockRuleVO.java:47-48）

-- 证据 4：默认值 '1' 与前端弹窗硬编码 '1'、后端缺省校验口径一致
--   （SanitationClockRecordServiceImpl.java:938-940：null/脏值/‘1’ 均默认校验围栏）

-- ----------------------------------------------------------------------------
-- 核验 SQL（只读，实施/验收阶段确认目标库结构用；本阶段未连接数据库，结果 not_run）
-- ----------------------------------------------------------------------------
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_COMMENT
FROM information_schema.columns
WHERE table_schema = DATABASE()
  AND table_name = 'sanitation_clock_rule'
  AND column_name = 'fence_required';
-- 预期（依据 db/jeebootx_sanitation.sql:206）：
--   fence_required | char(1) | YES | 1 | 是否校验围栏
