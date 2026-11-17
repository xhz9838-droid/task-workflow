# -*- coding: utf-8 -*-
"""HITL — MCP Server（stdio）：Agent 侧人工决策工具。

工具：
    request_human_decision  发起决策请求并**有界阻塞等待**用户回复
    get_human_decision      查询决策（恢复后取回用户决策）
    list_human_decisions    列出决策（含等待中的）

阻塞语义（关键）：
    - 工具内部轮询决策库（共享 SQLite），钉钉回复经 reply_handler 落库后即返回。
    - 等待超时（默认 300s）返回 outcome=suspended：Agent **必须停止**依赖该决策的
      后续操作并结束回合（安全挂起），决策记录持久化，随后由原 Session 恢复流程续跑。
    - 未获批准绝不返回 "approved"。

启动（Claude Code MCP 注册见 README）：
    python <repo>/agent-manager/human_decision/mcp_server.py
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)  # agent-manager/
for _p in (_PARENT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human_decision.decision_manager import DecisionManager  # noqa: E402

_manager: DecisionManager | None = None


def load_state_manager():
    """导入 agent-manager/state_manager，消解同名 `models` 歧义。

    state_manager 以裸模块名 `models` 引用 agent-manager/models.py，
    与 human_decision/models.py 同名；当 human_decision 目录排在 sys.path
    前面时会解析错模块（实测 ImportError → 桥接静默失效）。
    这里以显式文件位置加载 agent-manager/models.py 并注册为 `models`，
    再导入 state_manager。human_decision 包内均为
    `human_decision.models` 限定导入，不受影响。
    """
    if "state_manager" in sys.modules:
        return sys.modules["state_manager"]
    import importlib
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "models", os.path.join(_PARENT, "models.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["models"] = mod
    spec.loader.exec_module(mod)
    return importlib.import_module("state_manager")


def install_task_state_hook(mgr: DecisionManager, db_path: str | None = None) -> None:
    """T06 生产接线：决策生命周期 → agent-manager 任务状态桥（task_state_hook）。

    - 决策创建/进入等待 → 任务 WAITING_HUMAN
    - 决策闭环（complete）→ 任务 RUNNING（继续执行）
    - 无对应执行记录（独立测试任务、无 agent-manager 驱动）时静默跳过
    - 异常绝不影响决策主流程
    """

    def hook(*, task_id: str, state: str, decision_id: str = "") -> None:
        try:
            state_manager = load_state_manager()

            sm = state_manager.StateManager(db_path)
            try:
                live = ("RUNNING", "WAITING_HUMAN")
                rec = next(
                    (e for e in sm.list_executions()
                     if str(e.get("task_id")) == str(task_id)
                     and str(e.get("workflow_status")) in live),
                    None,
                )
                if rec is None:
                    return
                sm.update_execution(rec["id"], workflow_status=state)
                sm.log_event(rec["id"], "hitl_task_state",
                             {"state": state, "decision_id": decision_id})
            finally:
                sm.close()
        except Exception:
            pass

    mgr.task_state_hook = hook


def get_manager() -> DecisionManager:
    global _manager
    if _manager is None:
        _manager = DecisionManager()
        install_task_state_hook(_manager)
    return _manager


def build_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("human-decision")

    @mcp.tool()
    def request_human_decision(
        task_id: str,
        question: str,
        background: str = "",
        options: list[dict] | None = None,
        recommendation: str = "",
        recommend_reason: str = "",
        risk: str = "",
        level: str = "",
        project_key: str = "",
        wait_seconds: int = 0,
    ) -> dict:
        """发起人工决策请求并等待用户在钉钉回复。

        Args:
            task_id: 当前禅道/任务 ID
            question: 需要用户确认的问题
            background: 问题背景
            options: 方案列表，如 [{"id":"A","description":"..."}, {"id":"B","description":"..."}]
            recommendation: 推荐方案 id
            recommend_reason: 推荐原因
            risk: 不确认的风险
            level: 决策等级 P0/P1/P2（可空，自动检测；P0=必须批准）
            project_key: 项目 key（可空）
            wait_seconds: 有界等待秒数（0=用配置默认 300s）

        Returns:
            outcome=decided  → decision 字段含用户选择（reply_choice/reply_comment）
            outcome=suspended → 等待超时：**立即停止**依赖该决策的操作并结束回合，
                                在输出中注明任务挂起等待决策
        """
        mgr = get_manager()
        rec = mgr.create_decision(
            task_id=task_id, question=question, background=background,
            options=options or [], recommendation=recommendation,
            recommend_reason=recommend_reason, risk=risk,
            level=level or None, project_key=project_key,
            wait_seconds=wait_seconds or None,
        )
        result = mgr.wait_for_decision(rec.decision_id, wait_seconds=wait_seconds or None)
        result["decision_id"] = rec.decision_id
        return result

    @mcp.tool()
    def get_human_decision(decision_id: str) -> dict:
        """按 decision_id 查询决策记录（含用户回复与事件流）。恢复执行后用它取回决策。"""
        mgr = get_manager()
        d = mgr.get_decision(decision_id)
        if d is None:
            return {"found": False, "decision_id": decision_id}
        return {"found": True, "decision": d}

    @mcp.tool()
    def list_human_decisions(task_id: str = "", status: str = "", limit: int = 20) -> dict:
        """列出决策。task_id/status 可空。status 可填 WAITING_REPLY 等。"""
        mgr = get_manager()
        items = mgr.list_decisions(status=status or None, task_id=task_id or None, limit=limit)
        return {"count": len(items), "decisions": items}

    return mcp


def main() -> None:
    mcp = build_server()
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
