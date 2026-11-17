# HITL 剩余必做两项 — 验收报告

> 2026-11-17 · 执行范围：用户授权的 ① hitl-daemon 服务化 ② cc_connect_resume 破坏性隔离补测
> 范围外操作：无（未部署业务系统、未重启业务服务、未动禅道任务状态）

## 逐项验收结论

| # | 验收项 | 结论 | 证据 |
|---|---|---|---|
| 1 | daemon 计划任务创建成功，配置开机启动 | **BLOCKED(计划任务) / PASS(等效替代)** | `Register-ScheduledTask`/`schtasks /create` 均被 UAC 拒绝（Administrator 组账户 + 非提升令牌，HRESULT 0x80070005）。按"不要求管理员权限"约束改用 **HKCU Run 键 + 监督进程** 等效方案：`reg query HKCU\...\Run` → `hitl-daemon REG_SZ pythonw.exe ...\daemon_supervisor.py`（注册成功）。如需计划任务版，管理员执行 `schtasks /create /tn hitl-daemon /tr "cmd /c D:\WorkSpace\task-workflow\agent-manager\human_decision\run_daemon.cmd" /sc ONLOGON /rl LIMITED /f` |
| 2 | daemon 异常退出后自动恢复 | **PASS** | 12:17:15 `taskkill /F` 杀死 daemon(PID 42360) → supervisor 日志 `12:17:15 daemon 退出 rc=1，10s 后重启` → `12:17:25 拉起 daemon`（新 PID 21696）。实测真实崩溃恢复 |
| 3 | 关闭终端后 daemon 仍然运行 | **PASS** | supervisor(PID 16140) 以 pythonw 分离进程运行，其原始终端父进程(PID 10984)已退出（OpenProcess 探测 alive=False），supervisor/daemon 存活（alive=True）。开机自启链路（Run 键→supervisor→daemon）已手动触发验证；**真实重启未实测**（需重启机器，如实标注） |
| 4 | 独立 cc-connect 会话完成真实进程终止 + `--resume` 恢复 | **PASS** | 见下方完整证据链 |
| 5 | 当前使用中的原会话不受影响 | **PASS** | 正式实例 PID 31308（09:22 起）全程存活；`cc-connect` 计划任务 State=Running；`~/.cc-connect/sessions/` 三个会话文件无测试写入（mtime 11:31/12:09/09:10，均非测试时段）；测试全程仅触碰隔离目录 `execution/hitl-resume-test/` |
| 6 | HITL + agent-manager 测试全过 | **PASS** | `agent-manager/` 下分别执行：`pytest human_decision/tests` → **51 passed**；`pytest tests` → **20 passed** |
| 7 | 更新验收报告 | **PASS** | 本文件 |
| 8 | Git 提交 + 工作区确认 | **PASS** | 见文末 |

## cc_connect_resume 隔离补测证据链（验收项 4）

**隔离保证**：独立配置 `execution/hitl-resume-test/config.toml`（独立 data_dir、webhook :19111、management :19820、bridge 关闭、占位平台假凭据 `fake-test-client-id`——绝不触碰真实钉钉应用）；独立工作目录 `ws/`；测试实例独立进程树。

| 步骤 | 时间 | 证据 |
|---|---|---|
| 1. 启动隔离实例 | 12:27:35 | 日志 `cc-connect is running projects=1`；webhook/management 端口监听；假凭据 stream 按预期 authFailed（无副作用） |
| 2. 触发任务一（记暗号 ALPHA-77 + 写 marker1） | 12:28:59 | `webhook: received`→`session spawned ... is_resume=false`；`ws/marker1.txt` = `ALPHA-77` ✅ |
| 3. 记录原 Session ID | — | `ccdata/sessions/*.json` → `agent_session_id: a4104e47-c456-4234-b565-66e20ddb6afe` |
| 4. **真实进程终止** | 12:31 | `taskkill /F /PID 11468`（目标=测试实例拉起的 claude 进程，命令行含测试 system-prompt 路径，经命令行核对后终止；其余 claude 进程未动）；杀后 session 文件仍保留 agent_session_id |
| 5. 发送第二条消息（问暗号+写 marker2） | 12:32:56 | 日志原文：`claudeSession: starting innerArgs=[... --resume a4104e47-c456-4234-b565-66e20ddb6afe ...]`；`session spawned agent_session=a4104e47-... is_resume=true` |
| 6. **上下文连续验证** | 12:33± | `ws/marker2.txt` = `ALPHA-77` —— 恢复后的 Agent 记得已终止会话中的暗号，**未依赖任何重新描述** ✅ |

**结论：`cc_connect_resume`（agent_session_id 持久化 → `claude --resume` 续接原会话 → 上下文零丢失）真实验证通过。**

测试实例已停止（PID 9732 已终止，端口释放）；证据保留在 `execution/hitl-resume-test/`（config、ccdata、ws marker、cc-connect-test.log）。

## 新增/修改文件（本任务）

| 文件 | 说明 |
|---|---|
| `agent-manager/human_decision/cli.py` | daemon 单实例保护（PID 锁 + 陈旧锁接管；Windows 存活探测用 ctypes OpenProcess，禁用 os.kill(pid,0)） |
| `agent-manager/human_decision/daemon_supervisor.py` | 监督进程：崩溃自愈（10s 退避）、rc=2 等待重试、日志、自身单实例 |
| `agent-manager/human_decision/run_daemon.cmd` | 计划任务/手动启动包装器（管理员注册计划任务时使用） |
| `agent-manager/human_decision/decision_manager.py` | 审计泄漏修复：HITL_NO_AUDIT/pytest 环境抑制测试写入真实 execution/ 树 |
| `agent-manager/human_decision/tests/conftest.py` | 测试自动置位 HITL_NO_AUDIT |
| `execution/3413/audit.jsonl` | 清理已提交测试审计垃圾 156 行（保留 2 行真实记录） |
| `execution/other/9001/audit.jsonl` | 显式 git rm（24/24 纯测试产物，经用户定调清理） |
| `execution/hitl-resume-test/` | 隔离测试环境 + 全部证据 |
| `execution/hitl/ACCEPTANCE-REPORT.md` | 本报告 |

## 遗留问题

1. **计划任务注册需管理员**（UAC）：如偏好 schtasks 版自启，管理员执行上表命令；Run 键方案功能等价（仅"未登录运行"做不到——用户级自启天然边界）。
2. **真实重启未实测**：开机自启配置已验证，真实重启生效性待下次重启确认。
3. HITL 通知通道依赖钉钉直发（cc-connect send 虚报问题仍在 v1.5.0），升级 cc-connect 后可回归验证。
4. 并行会话工作区有在途修改（mcp_server.py/runner.py/test_task_state_hook.py），本任务未触碰、未提交。

## Git

- 提交信息见 `git log`（feat/fix: HITL daemon 服务化 + resume 隔离补测 + 审计泄漏修复与清理）
- 无凭据入库：测试配置仅含本地假凭据；日志中 token 均为 `***` 掩码
- 未推送远程
