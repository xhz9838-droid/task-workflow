@echo off
REM HITL daemon 计划任务包装器（单实例由 cli.py 锁文件保证）
REM 日志追加到 agent-manager\logs\hitl-daemon.out.log（无事件时几乎不增长）
REM
REM 工作流根定位：优先环境变量 WORKFLOW_HOME，回退脚本自身推导（相对位置）。
REM 部署时无需改本文件——它从自身位置定位工作流根。

setlocal
set "SCRIPT_DIR=%~dp0"
REM SCRIPT_DIR 形如 ...\工作流根\agent-manager\human_decision\
REM 工作流根 = 上溯两级（human_decision -> agent-manager -> 工作流根）
for %%I in ("%SCRIPT_DIR%..\..") do set "WORKFLOW_ROOT=%%~fI"
if defined WORKFLOW_HOME set "WORKFLOW_ROOT=%WORKFLOW_HOME%"

cd /d "%WORKFLOW_ROOT%"
python agent-manager\human_decision\cli.py daemon --interval 3 >> agent-manager\logs\hitl-daemon.out.log 2>&1
exit /b %ERRORLEVEL%
