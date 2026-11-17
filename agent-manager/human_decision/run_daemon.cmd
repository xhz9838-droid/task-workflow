@echo off
REM HITL daemon 计划任务包装器（单实例由 cli.py 锁文件保证）
REM 日志追加到 agent-manager\logs\hitl-daemon.out.log（无事件时几乎不增长）
cd /d D:\WorkSpace\task-workflow
python agent-manager\human_decision\cli.py daemon --interval 3 >> agent-manager\logs\hitl-daemon.out.log 2>&1
exit /b %ERRORLEVEL%
