# HITL + Agent Execution Manager 验收报告

> 2026-11-17 · 基线 f50da7e · 本次为**生产运行环境最终验收**（A01/A02 真实环境验证 + 真实任务运行观察）
> 测试基线：HITL 56 + agent-manager 20 = **76 PASS / 0 FAIL**（较 f50da7e 的 68 新增 8 个：桥接 3 + DEC-ID 回归 5）

## 〇、现状核对结论（与上一版报告的差异修正）

### cc-connect 服务化真相：**已服务化，经 Windows 计划任务**（上一版"未服务化"结论错误）

| 项 | 实测 |
|---|---|
| 注册方式 | **计划任务 `cc-connect`**（非 SCM 服务，故 `sc query` 报 1060 被误判为"未服务化"） |
| 当前状态 | `State=Running`；进程链 `wininit → services.exe → svchost → powershell → cc-connect.exe`（PID 31308） |
| 触发器 | `MSFT_TaskLogonTrigger`（Administrator 登录自启，Enabled） |
| 启动脚本 | `C:\Users\Administrator\.cc-connect\cc-connect-daemon.ps1`：while(true) 守护循环，进程退出非 0 时 10 秒自动拉起（崩溃自愈） |
| 运行用户 | `DESKTOP-L85DMM0\Administrator`（Interactive，RunLevel Limited） |
| 工作目录 | `C:\Users\Administrator\.cc-connect`（Set-Location） |
| 环境 | daemon 脚本显式注入 PATH（含 Node/Python/npm-global），`CC_LOG_FILE/CC_LOG_MAX_SIZE/CC_LOG_MAX_BACKUPS` |
| Claude Code MCP | 用户级 `~/.claude.json` 注册 `human-decision`（`python -I <绝对路径>`）✔ Connected；工作目录 D:\WorkSpace 亦可加载（cc-connect 实际场景） |
| 日志 | `~/.cc-connect/logs/cc-connect.log`（10MB×3 轮转） |

**结论修正**：A01 的"cc-connect 服务化"不是待办项，而是**已实现**（计划任务 + daemon 守护）。上一版报告据 `sc query 1060` 判定"未服务化"属**证据误读**，本版更正。

**附带风险**：计划任务 `ExecutionTimeLimit=PT72H` 且 `RestartCount=0`——任务连续运行 72 小时后会被计划任务终止且不自动重启（仅 daemon 进程内循环受保护，不覆盖任务级终止）。建议后续把该任务改为 `ExecutionTimeLimit=PT0S`（不限时）。

## 一、A01 运行环境验收（最终：PASS）

| # | 验收项 | 结果 | 真实环境证据（2026-11-17） |
|---|---|---|---|
| 1 | cc-connect 服务存在且正常运行 | ✅ PASS | 计划任务 State=Running；cc-connect.log `dingtalk: stream connected client_id=dingwv9ffps0iiy5spqy` + `engine started`；今日多条真实收发记录 |
| 2 | 服务重启后能够正常工作 | ✅ PASS | **今日 09:21:46 发生真实重启**（计划任务重新运行，engine 09:22:07 就绪）；重启后 09:29–09:30 真实钉钉 E2E-3 全链路成功（通知→回复→恢复）。另：daemon 守护循环可崩溃自愈（配置证据）。**未为测试重复重启**（遵守"不中断现有服务"约束，以真实重启后行为为证） |
| 3 | 能够接收钉钉私聊消息 | ✅ PASS | cc-connect.log 今日 09:23/09:24/09:30/11:31/12:41 多条 `message received ... user=徐弘祖`（真实私聊） |
| 4 | 能够启动 Claude Code | ✅ PASS | `session spawned ... turn complete`（agent_session=ac2d8b92 等）；本次验收经 runner 启动 claude 子进程 4 次成功 |
| 5 | Claude Code 能加载 human-decision MCP | ✅ PASS | `claude mcp list` ✔ Connected（repo 根与子目录均可）；无头 `claude -p` 实调 `list_human_decisions`/`request_human_decision` 成功（本报告 A02 证据） |
| 6 | HITL 配置能够正确加载 | ✅ PASS | 分层加载实测：DEFAULTS→hitl.yaml→hitl.local.yaml（gitignored，含本人 userId）→env；fail-closed 生效（deciders 白名单、any_private_chat_user=false） |
| 7 | userId 身份校验正常 | ✅ PASS | 实测 5 例：授权 ID（watch/hook）放行；陌生 ID 99999/88888 拒绝；空 ID 拒绝；群聊无权威 ID 拒绝。真实链路见 A02-R1（徐弘祖实名通过）与 R3（fail-closed 拒绝） |

## 二、本次发现并修复的缺陷（4 项，均属"必要缺陷修复"）

### D4 · task_state_hook 从未接线（决策↔任务状态桥生产失效）
`DecisionManager._notify_task_state` 预留了 `task_state_hook` 回调，但**全仓无任何生产代码赋值**——T06 的 WAITING_HUMAN 桥只在单测手动注入时生效，真实运行不更新任务状态（`waiting` CLI 的"任务级 WAITING_HUMAN"永远为空）。
**修复**：`mcp_server.py` 新增 `install_task_state_hook()`（决策创建→任务 WAITING_HUMAN，complete→RUNNING；无执行记录静默跳过；异常不影响决策）+ `load_state_manager()` 消解 `models` 同名歧义（agent-manager/models.py 与 human_decision/models.py 同名，直接 `from state_manager import` 会解析错模块——测试先行发现）。
**验证**：新增 3 个测试（51 HITL 全绿）；真实链路 A02-R1 实测 `hitl_task_state: WAITING_HUMAN` 事件落库（execution_events）。

### D5 · runner 启动命令缺 `--verbose`（stream-json 直接报错）+ 缺受控权限参数（MCP 工具被拒）
`claude -p --output-format stream-json` 硬性要求 `--verbose`，否则 CLI 报错退出；且无 `--permission-mode/--allowedTools` 时无头运行无法调用 MCP 工具（授权提示在 -p 模式直接拒绝）。`docs/execution/integration-plan.md` 约定的启动形态未被实现。
**修复**：`runner.py` 补 `--verbose` + `default_claude_flags()`（默认 acceptEdits + 最小白名单 `mcp__human-decision`，`CLAUDE_RUNNER_FLAGS` 可覆盖）。
**验证**：`claude -p` 实测（错误/修复对照）+ A02-R1 真实闭环。

### D6 · 多行 prompt 经 cmd.exe（claude.CMD 垫片）传参损坏（runner 无法运行任何真实工作流）
Windows 下 subprocess 启动 `claude.CMD` 经 cmd.exe 解析命令行，**argv 中的多行 prompt 被换行截断/损坏**——实测 agent 只收到第一行甚至无输出、无 result 事件，但退出码 0（被误记 SUCCEEDED）。任何真实 prompt 均为多行 → runner 完全不可用。
**修复**：prompt 改经 **stdin** 传入（`claude -p` 从 stdin 读取），argv 不再携带 prompt。
**验证**：多行探针对照（argv 损坏 / stdin 完好，AAA+BBB 标记均复现）+ A02-R1 用 20 行 prompt 真实闭环成功。

### D7 · runner 输出泵日志行未持久化（遗留，未修）
`_start_output_pump` 读取子进程输出（`last_output_at` 更新正常，监控有效），但 `[out]/[err]` 日志行未出现在 CLI 输出/重定向文件（线程 print 本身验证正常，原因未定位）。**影响**：执行过程文本无留痕（DB 事件/状态不受影响）。**建议**：后续把 pump 输出写独立日志文件（属 runner 增强，超出本次"必要修复"范围，留待下轮）。

### D8 · DEC-ID 正则截断多段任务号（显式决策绑定失效）
`DEC_ID_RE = \b(DEC-[A-Za-z0-9]+-\w+)\b` 只捕获单段任务号：`DEC-HITL-A02-3-13484101` 被截断成 `DEC-HITL-A02` → 「未找到决策」→ **多决策并行时的显式编号绑定完全不可用**（历史 E2E 的 DEC-HITL-E2E-* 同样受影响，只是从未走显式绑定）。
**修复**：改为 `\b(DEC-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)\b`（DEC- 后任意多段；DEC- 形状的无效编号仍回「未找到决策」而非「无法识别」）。
**验证**：新增 5 例回归（含既有 test_multiple_decisions_parallel 兼容）；R3 陌生身份用例经显式绑定确定性复现拒绝。

### 关联处置：审计测试泄漏（跨会话）
- f50da7e 提交中含 ~150+ 行测试审计垃圾（`execution/3413/audit.jsonl`、`execution/other/9001/audit.jsonl`）——按用户定调**留给并行会话（task-workflow-a9）清理并显式提交**，本次不动已提交内容。
- 并行会话清理时误删 `execution/other/9001/audit.jsonl` 的 24 行已提交内容——已按最小干预 `git checkout HEAD --` **恢复**。
- 泄漏根因已由并行会话修复（`HITL_NO_AUDIT`/pytest 抑制 + conftest 自动置位）；本会话测试不新增泄漏（A02 审计仅落 `execution/hitl-e2e/` 未跟踪目录）。

## 三、测试基线（2026-11-17 复测）

| 套件 | 数量 | 结果 |
|---|---|---|
| HITL（human_decision/tests/，含新增 test_task_state_hook.py×3、test_dec_id_parse.py×5） | 56 | ✅ PASS |
| agent-manager（tests/） | 20 | ✅ PASS |
| **合计** | **76** | **PASS / 0 FAIL** |

> 注：两套件需分别运行（同名 `models` 在一次 pytest 会话内冲突，属测试基建问题，非产品缺陷）。

## 四、A02 真实钉钉 E2E（独立测试任务 hitl-e2e / HITL-A02-*）

运行方式：agent-manager runner（真实启动 claude 子进程）+ CC_SESSION_KEY 绑定真实单聊会话；决策通知经钉钉官方 API 直发；回复经 cc-connect 会话文件 watch 路径入库。全程独立测试任务，不影响业务任务。

### R1 核心闭环 + 重复回复（task HITL-A02-1）——✅ 核心闭环 PASS

| 时间 | 事件 | 证据 |
|---|---|---|
| 12:41:23 | runner 启动 Agent（pid 42900，execution#3） | agent_runs.id=3 |
| 12:41:31 | Agent 调用 request_human_decision（P1，A/B 两方案） | DEC-HITL-A02-1-12413101 created |
| 12:41:32 | 钉钉私聊通知送达 + **任务状态→WAITING_HUMAN** | notified_at；execution_events `hitl_task_state` |
| 12:41:48 | 授权用户回复 `A`（徐弘祖 / 17248148409976157），身份校验通过 | reply_accepted（source=watch，msg_id 落库） |
| 12:41:48 | **live_continue** 原 Session 恢复（阻塞工具轮询决策库取回） | resumed 事件 |
| 12:41:53 | Agent 继续执行并闭环决策（complete CLI）→ COMPLETED | status=COMPLETED |
| 12:41:59 | Agent 正常结束，runner 记录 SUCCEEDED | agent_finished exit=0 |
| — | outcome 文件 | reports/hitl-a02-1-outcome.md：结论 OK-A |

**A02 九项对照（R1）**：①Agent 调用工具 ✅ ②钉钉私聊通知 ✅ ③Agent 进入 WAITING_HUMAN（任务级桥接实证）✅ ④授权用户回复 ✅ ⑤发送者 userId 校验 ✅ ⑥决策记录持久化（3 表 + 事件流）✅ ⑦原 Session 恢复（live_continue）✅ ⑧继续执行并完成 ✅ ⑨任务状态与决策状态一致（WAITING_REPLY↔WAITING_HUMAN；完成后 COMPLETED↔SUCCEEDED）✅

### T2 重复回复拦截 —— ✅ PASS（13:37 真实钉钉）

| 行 | 时间 | 内容 | 结果 |
|---|---|---|---|
| #14 | 12:41:48 | `A`（首次，msg_id=5953a9ee…） | accepted=1，决策生效 |
| #15 | 13:37:21 | `A`（重复，msg_id=9a8e3abd…，不同消息） | **accepted=0**，reject_reason=`决策状态 COMPLETED 不可回复` + `reply_rejected` 事件 |

决策状态未被重复回复改变（保持 COMPLETED / user_reply=A）。经 daemon watch **生产链路**自动处理（source=watch）。
**结论**：重复回复幂等拦截真实生效（D2 的 msg_id 去重 + 状态机防重双层均在真实通道验证）。

### R2 无效回复拦截（HITL-A02-2）—— ✅ PASS（13:43 真实钉钉）

| 时间 | 事件 | 证据 |
|---|---|---|
| 13:38:23 | 决策创建并通知（DEC-HITL-A02-2-13382201）+ 任务 WAITING_HUMAN | hitl_task_state 事件 |
| 13:43:27 | 用户发送无效回复 `hhh` | **accepted=0**，reject_reason=「请按约定回复：选项字母（如 A）、C + 自定义意见、STOP 或 &lt;决策编号&gt; &lt;回复&gt;」+ reply_rejected 事件；用户收到"无法识别的回复"回执；决策保持等待 |
| 13:43:34 | 用户发送 `B` | accepted=1 → DECISION_RECEIVED → RESUMED（live_continue） |
| 13:43:39 | Agent 继续执行并闭环 | COMPLETED；outcome=OK-B |

**结论**：无效回复被严格解析拦截（9e7a892 修复真实生效），不污染决策；随后合法回复正常生效。

### R3 未授权用户拒绝 fail-closed（HITL-A02-3）—— ✅ 真实链路拒绝 PASS｜⚠️ 跨真实账号场景 BLOCKED（账号限制）

R3 决策在 fail-closed 白名单（不含真实用户）下创建：

| 证据 | 结果 |
|---|---|
| **真实钉钉回复**（13:49:05，用户 `A`） | **accepted=0**，reject_reason=「身份校验失败: 用户 17248148409976157 不在授权决策人白名单」（source=watch 生产链路）；决策保持 WAITING_REPLY，未放行 |
| **陌生身份 99999**（完整 handle 链路，显式 DEC-ID 绑定） | outcome=rejected，同一拒绝理由（确定性复现） |
| **Agent 行为** | 150s 有界等待到期 → **SUSPENDED**，未自动放行（不采纳推荐方案），outcome 文件如实记录 |
| 跨真实账号发送者 | **BLOCKED**——仅一个真实钉钉账号，无法产生第二真实发送者（按约定不伪造 PASS） |

**架构观察（如实）**：授权白名单是**处理进程级**配置（hitl.local.yaml/env），非决策级。本例真实回复被拒是 fail-closed 进程先于全局放行配置的 daemon 处理（2s vs 3s 轮询竞速）；若 daemon 先处理则会被接受（该用户在全局配置中属授权人）。纯"全局白名单外用户"场景由 99999 用例确定性覆盖。

### R4 有界等待安全挂起 / 超时提醒（HITL-A02-4 / 4B / 4C）—— ⚠️ PARTIAL（决策侧证据成立；工具挂起产线两度被用户惯性回复抢先，重跑被用户叫停）

| 轮次 | 结果 | 事实 |
|---|---|---|
| R4（13:58） | 超时路径未行使 | 用户在 12s 内惯性回复 `A`（响应上一轮指令），被正确绑定采纳——绑定/授权/采纳链路本身正常，非产品缺陷 |
| R4B（14:01） | 超时路径未行使 | 同上（12s 内惯性回复，daemon 竞速采纳）；防误触盾（fail-closed 白名单）被全局放行配置的 daemon 绕过——见 R3 架构观察 |
| R4C（14:04） | **决策侧证据成立** | 非绑定决策（不绑定聊天会话键，闲聊回复无法触达）：决策创建后保持 **WAITING_REPLY**、**无任何放行**、`auto_approved` 从未触发；runner 运行于 14:07 被**系统内存压力**终止（Claude Code bg shell pressure reap，非产品故障），工具挂起 outcome 未产出 |
| 超时提醒 | 真实通道证据 | 历史：E2E-2 提醒真实送达（2026-11-16 21:08:23，created+30min 精确触发，reminded 事件）；R4C 提醒阈值 14:34:32 由 daemon 自然触发（同一 timeout_handler 真实链路） |

**用户决定（2026-11-17）**：停止反复测试，不再重跑 R4C；剩余验证转入真实任务全流程测试。
**铁律核验**：三轮均**未出现自动批准**——超时/挂起语义（不自动放行）在决策侧成立；工具级 suspended 产线有 R3 的 150s 真实挂起先例（SUSPENDED outcome + 不放行）。

### R5 多任务决策隔离（HITL-A02-5A/5B 并行）—— ⏭️ NOT_RUN（用户决定停止反复测试，转入真实任务阶段验证）

D8 修复后显式 DEC-ID 绑定已具备能力（回归测试通过）；隔离语义另有历史真实证据（E2E-1/2 的重复回复全部被「决策已处理」拦截、不串新任务）。多决策并行隔离留待真实任务阶段自然覆盖。

### A02 测试运行统计（供观察参考）

| 指标 | 值 |
|---|---|
| runner 启动次数 | 8（R1×3：2 次为缺陷暴露跑 + 1 成功；R2/R3/R4/R4B/R4C 各 1） |
| 成功完成 | 5（R1/R2/R3/R4/R4B） |
| Agent 异常退出 | 1（R4C，系统内存压力回收） |
| HITL 决策次数 | 6（A02-1/2/3/4/4B/4C） |
| 真实钉钉闭环 | 4（A02-1/2/4/4B，均 live_continue） |
| 平均闭环耗时 | ~30s（通知→回复→恢复，最快 12s） |
| 重复执行/状态不一致 | 0（决策↔任务状态无一处背离） |

## 五、真实任务运行观察 —— ⏭️ 转入下一阶段（用户决定：真实任务测试整个流程优先）

**用户决定（2026-11-17）**：不再进行合成测试轮次；后续以**真实任务跑完整研发流程**（zentao-dev-workflow 全链路）作为更重要的验证。

**已准备的候选与前置条件**：
- 禅道账号 `xuhongzu` 名下**无未完成任务**（仅 1 已关闭）；7 个活跃 Bug 候选（小助手-移动端类，pri 2-3，如 #3264 区域经济年度经济移动端报错）
- **前置条件（不满足不可开工，按硬约束不猜测）**：真实任务需 `config/projects/{key}.yaml` 仓库/技术栈映射；现有配置仅 `jeebootx`/`demo-react`，**小助手产品无项目配置**——需要您确认 ①跑哪个任务/由 Bug 建任务 ②对应仓库路径与项目 key ③是否补项目配置
- 建议路径：zentao-tasks 建小任务（建前列清单经您确认）→ `runner.py run --project <key> --task-id <id>` 走 `/zentao-dev-workflow` 全流程 → HITL 决策经钉钉闭环 → 观察统计（任务数/成功/失败/异常退出/重试/恢复/决策次数/耗时/一致性）
- 本阶段为 A02 建立的真实链路与修复（D4-D8）将直接支撑该阶段；R5 隔离、R4 工具挂起等未尽项在真实任务中自然覆盖

## 六、遗留风险

1. **计划任务 72h 限时**：`cc-connect` 任务 `ExecutionTimeLimit=PT72H`、`RestartCount=0`，超时被终止不自启（建议改 PT0S，属计划任务配置调整，本次未动）。
2. **D7 runner 输出未持久化**（见上）。
3. **complete 经 CLI 不触发任务桥**：`human_decision/cli.py` 的 DecisionManager 未安装 task_state_hook（该文件正由并行会话修改中，避免写冲突未动）——`complete` 后任务状态在 Agent 退出前短暂停留 WAITING_HUMAN（秒级窗口，runner 收尾会统一置终态）。建议并行会话在其 daemon/CLI 收尾时调用 `mcp_server.install_task_state_hook`。
4. **MCP 双注册作用域冲突告警**：`.mcp.json`（项目级相对路径）与用户级绝对路径并存，`claude mcp list` 报 conflicting scopes（功能正常：repo 根走项目级、其它目录走用户级；建议后续统一）。
5. **长时间超时标记（timeout_after=86400s）与 30 分钟提醒**：无法在验收窗口内真实等到（超时提醒有历史真实证据，见 A02 额外验证）。
6. 并行会话仍在运行 hitl-daemon 服务化与 cc_connect_resume 隔离补测（其范围），`cc_connect_resume` 二级恢复的真实隔离证据以该会话报告为准。

## 七、结论

| 问题 | 回答 |
|---|---|
| 1. HITL 可稳定投入日常使用？ | **PASS（有条件）** — 核心闭环（通知/回复/身份/持久化/恢复/闭环）真实钉钉多轮验证通过；条件=遗留风险 1-3 项知悉（72h 计划任务限时、complete-CLI 桥接窗口、白名单为进程级配置） |
| 2. 团队成员可独立配置使用？ | **PASS** — hitl.local.yaml + env 覆盖，gitignore 已验证 |
| 3. Agent 失败后能正确发现通知？ | **PASS** — FailureDetector 8 类 + 真实通知链路 |
| 4. 可有限自动重试？ | **PASS** — TRANSIENT 重试、HITL/永久不重试 |
| 5. 重启后正确恢复任务？ | **PASS** — 今日真实重启后全链路实测正常（A01-2） |
| 6. 影响正式使用的风险？ | 见"六、遗留风险"；**重大修复 D4-D8 已落地**（状态桥接、runner 可用性、DEC-ID 绑定） |
| 7. 适合团队日常使用？ | **可以进入真实任务试运行**——合成验证已覆盖关键面，按用户决定转入真实任务全流程测试作最终磨合 |

## 验收项汇总（A01-A10）

| 编号 | 项 | 结果 |
|---|---|---|
| A01 | HITL 运行环境 | **PASS**（7/7 项，含服务重启后行为真实验证；服务化=计划任务+daemon） |
| A02 | 私聊决策闭环 | **PASS（部分项按用户决定收束）**：核心闭环/重复拦截/无效拦截/未授权拒绝 PASS（R1/T2/R2/R3）；R4 超时挂起 PARTIAL（决策侧铁律成立，工具挂起产线两度被惯性回复抢先，R4C 运行被系统内存压力终止后按用户决定不重跑）；R5 隔离 NOT_RUN（转入真实任务阶段）；跨真实账号场景 BLOCKED（账号限制） |
| A03 | 团队本地配置 | **PASS** |
| A04 | 身份安全 | **PASS**（fail-closed + 真实拒绝证据见 R3；白名单为进程级配置的架构观察已记录） |
| A05 | Agent 失败检测 | **PASS**（8 类 + D5/D6 修复后失败不再被误报成功） |
| A06 | 有限自动重试 | **PASS** |
| A07 | 状态持久化 | **PASS** |
| A08 | 重启恢复 | **PASS** |
| A09 | 并发隔离 | **PASS（机制层）** — msg_id UNIQUE + 任务锁 + 状态机防重（T2 真实证据）；D8 修复显式绑定能力；多决策并行实测转入真实任务阶段 |
| A10 | 测试与文档 | **PASS**（76 测试 + 本报告） |

## 八、Git 交付（本阶段）

- **修复**：`runner.py`（D5/D6：--verbose + 受控权限 + stdin 传 prompt）、`cli_util.py`（日志 flush）、`mcp_server.py`（D4：task_state_hook 生产接线 + models 消歧加载）、`decision_detector.py`（D8：DEC-ID 多段绑定）
- **测试**：新增 `test_task_state_hook.py`（3）、`test_dec_id_parse.py`（5）；基线 56+20=**76 PASS / 0 FAIL**
- **报告与证据**：本报告 + `reports/hitl-a02-*`（prompt/outcome/runner log 真实证据）
- 不推送远程；并行会话（task-workflow-a9）的工作区修改未纳入本次提交
