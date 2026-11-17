# HITL A02-R4 超时挂起测试结果

- 用例：A02-R4（有界等待安全挂起，不自动批准）
- task_id: HITL-A02-4
- project_key: hitl-e2e
- level: P1
- wait_seconds: 60

## 结论

**FAIL-AUTO-APPROVED**（outcome=decided，异常分支；预期 outcome=suspended）

## 事实记录（如实）

- 决策编号：<decision_id> = `DEC-HITL-A02-4-13584501`
- outcome=`decided`（预期 `suspended`，未出现超时挂起）
- decision.status=`RESUMED`
- created_at=2026-11-17T13:58:45+08:00
- replied_at=2026-11-17T13:58:57+08:00（等待约 12 秒即返回，未走满 60 秒超时挂起路径）
- user_reply=`A`，reply_kind=`option`，reply_choice=`A`，reply_comment=null
- reply_user_id=`17248148409976157`，reply_user_name=`徐弘祖`
- resume_method=`live_continue`

## 关键校验点

- 未获批准绝不放行（auto_approved 应为 False）：本次 outcome=decided 且带明确回复人
  （徐弘祖）与回复内容（A），从返回数据看决策来自真实人工回复，而非静默自动批准；
  但用例预期为「无人回复→超时 suspended」，实际未进入挂起路径，故按测试判定记 FAIL。
- 若后续核实该回复为系统自动产生而非人工，则升级为真实缺陷（自动批准）。

## 结束

未修改其他文件；未调用 complete。

---
【验收方注解 2026-11-17】本例 decided 来源是**用户真实回复**（13:58:57 惯性回复 A，早于 60s 窗口），
并非自动批准——auto_approved 从未触发。"FAIL-AUTO-APPROVED" 标签应读作"超时路径未行使"。
已用 fail-closed 防误触盾重跑（HITL-A02-4B），见 hitl-a02-4b-outcome.md。
