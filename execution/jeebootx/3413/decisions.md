# 任务 3413 决策记录（ADR）

## D-3413-001 · 跳过前端构建

- **时间**: 2026-11-16 17:46
- **级别**: L2（范围调整，授权范围内自选）
- **决策**: QA1 验收阶段跳过 `npm run build`（vite build）
- **背景**: 前端构建耗时较长，用户明确指令跳过
- **影响范围**:
  - QA1 报告中 build 项记 `not_run`，reason 写「用户指令跳过前端构建」
  - 依赖 build 才能验证的验收项标 `blocked`，不标 pass
  - eslint 静态检查、静态代码验收（AC3/AC5/AC10）、字段对齐、契约一致性、NF1-5 全部保留
- **可逆**: 是（后续可单独执行 build 补验）
- **记录人**: main agent（workflow continuation protocol 规则 2）
