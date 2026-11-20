# -*- coding: utf-8 -*-
"""P11.1 CLI 测试 —— 参数解析、退出码、边界场景、Windows 兼容。

纯 Mock（`--dry-run`），不启动真实开发任务、不触发 Jenkins、不写禅道。

运行：python -I agent-manager/tests/test_cli.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_AM = os.path.dirname(_HERE)
for p in (_AM, _HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from cli_util import (  # noqa: E402
    EXIT_BLOCKED,
    EXIT_FAILED,
    EXIT_LOCKED,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    load_config,
    table,
    truncate,
)
from cli import build_monitor_parser, build_runner_parser, monitor_main, runner_main  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, PASS if cond else FAIL, detail))
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def section(t: str) -> None:
    print(f"\n=== {t} ===")


DB = os.path.join(tempfile.mkdtemp(), "cli.db")


# --------------------------------------------------------------- 参数解析
def test_argparse() -> None:
    section("CLI 参数解析")
    rp = build_runner_parser()

    a = rp.parse_args(["run", "--project", "jeebootx", "--task-id", "3413"])
    check("run 必填参数解析", a.command == "run" and a.project == "jeebootx" and a.task_id == "3413")

    a2 = rp.parse_args(["run", "--project", "p", "--task-id", "t", "--dry-run",
                        "--no-subagents", "--skip-build", "--static-only", "--force",
                        "--level", "S", "--complexity", "high", "--files-count", "5"])
    check("run 可选参数解析", a2.dry_run and a2.no_subagents and a2.skip_build
          and a2.static_only and a2.force and a2.level == "S")

    a3 = rp.parse_args(["status", "--task-id", "3413", "--project", "jeebootx", "--json"])
    check("status 参数解析", a3.command == "status" and a3.json)

    a4 = rp.parse_args(["history", "--task-id", "3413"])
    check("history 参数解析", a4.command == "history")

    a5 = rp.parse_args(["list", "--project", "p"])
    check("list 参数解析", a5.command == "list" and a5.project == "p")

    mp = build_monitor_parser()
    m1 = mp.parse_args(["--task-id", "3413", "--project", "jeebootx"])
    check("monitor 参数解析", m1.task_id == "3413" and m1.project == "jeebootx")
    m2 = mp.parse_args(["--list", "--json"])
    check("monitor --list 解析", m2.list and m2.json)

    # 缺必填 → SystemExit(2)
    try:
        rp.parse_args(["run", "--project", "p"])  # 缺 --task-id
        check("run 缺必填报错", False, "未抛出")
    except SystemExit as e:
        check("run 缺必填报错", e.code == EXIT_USAGE, f"code={e.code}")


# --------------------------------------------------------------- 退出码
def test_exit_codes() -> None:
    section("退出码约定")
    check("EXIT_OK=0", EXIT_OK == 0)
    check("EXIT_FAILED=1", EXIT_FAILED == 1)
    check("EXIT_USAGE=2", EXIT_USAGE == 2)
    check("EXIT_NOT_FOUND=3", EXIT_NOT_FOUND == 3)
    check("EXIT_LOCKED=4", EXIT_LOCKED == 4)
    check("EXIT_BLOCKED=5", EXIT_BLOCKED == 5)

    # runner 无子命令 → 用法
    rc = runner_main([])
    check("runner 无子命令 → EXIT_USAGE", rc == EXIT_USAGE, f"rc={rc}")

    # monitor 无参数 → 用法
    rc2 = monitor_main([])
    check("monitor 无参数 → EXIT_USAGE", rc2 == EXIT_USAGE, f"rc={rc2}")


# --------------------------------------------------------------- run
def test_run() -> None:
    section("run 启动（dry-run Mock）")
    rc = runner_main(["run", "--project", "demo", "--task-id", "T-1",
                      "--description", "修改按钮文案 css 样式",
                      "--files", "src/x.vue", "--files-count", "1",
                      "--dry-run", "--db", DB, "--quiet"])
    check("run dry-run 成功", rc == EXIT_OK, f"rc={rc}")

    # 分级正确性（S → 0 agent）
    from state_manager import StateManager

    sm = StateManager(DB)
    rec = sm.get_execution("demo", "T-1")
    check("S 级记录正确", rec is not None and rec["task_level"] == "S",
          f"level={rec.get('task_level') if rec else None}")
    sm.close()

    # 用户禁子 Agent
    rc2 = runner_main(["run", "--project", "demo", "--task-id", "T-2",
                       "--description", "跨仓库复杂", "--files-count", "10",
                       "--repos", "a,b,c", "--complexity", "high",
                       "--no-subagents", "--dry-run", "--db", DB, "--quiet"])
    check("run 用户禁子 Agent 成功", rc2 == EXIT_OK, f"rc={rc2}")
    sm = StateManager(DB)
    rec2 = sm.get_execution("demo", "T-2")
    check("L 级记录正确", rec2 is not None and rec2["task_level"] == "L",
          f"level={rec2.get('task_level') if rec2 else None}")
    sm.close()


# --------------------------------------------------------------- 边界
def test_edge_cases() -> None:
    section("边界场景")

    # 1) status 任务不存在
    rc = runner_main(["status", "--task-id", "NOPE", "--db", DB, "--quiet"])
    check("status 不存在 → EXIT_NOT_FOUND", rc == EXIT_NOT_FOUND, f"rc={rc}")

    # 2) 已完成任务不重复执行
    rc2 = runner_main(["run", "--project", "demo", "--task-id", "T-1",
                       "--dry-run", "--db", DB, "--quiet"])
    check("已完成任务不重复执行 → EXIT_BLOCKED", rc2 == EXIT_BLOCKED, f"rc={rc2}")

    # 3) --force 覆盖
    rc3 = runner_main(["run", "--project", "demo", "--task-id", "T-1",
                       "--dry-run", "--force", "--db", DB, "--quiet"])
    check("--force 覆盖 → EXIT_OK", rc3 == EXIT_OK, f"rc={rc3}")

    # 4) history 不存在
    rc4 = runner_main(["history", "--task-id", "NOPE", "--db", DB, "--quiet"])
    check("history 不存在 → EXIT_NOT_FOUND", rc4 == EXIT_NOT_FOUND, f"rc={rc4}")

    # 5) monitor 不存在
    rc5 = monitor_main(["--task-id", "NOPE", "--db", DB, "--quiet"])
    check("monitor 不存在 → EXIT_NOT_FOUND", rc5 == EXIT_NOT_FOUND, f"rc={rc5}")

    # 6) list 空库
    empty_db = os.path.join(tempfile.mkdtemp(), "empty.db")
    rc6 = runner_main(["list", "--db", empty_db, "--quiet"])
    check("list 空库 → EXIT_OK", rc6 == EXIT_OK, f"rc={rc6}")


# --------------------------------------------------------------- 任务锁
def test_lock() -> None:
    section("重复启动保护")
    from state_manager import StateManager

    db = os.path.join(tempfile.mkdtemp(), "lock.db")
    sm = StateManager(db)
    ok1 = sm.acquire_lock("demo", "LOCK-1", os.getpid())
    check("获取锁", ok1 is True)
    sm.close()

    rc = runner_main(["run", "--project", "demo", "--task-id", "LOCK-1",
                      "--dry-run", "--db", db, "--quiet"])
    check("锁占用时拒绝启动 → EXIT_LOCKED", rc == EXIT_LOCKED, f"rc={rc}")

    rc2 = runner_main(["run", "--project", "demo", "--task-id", "LOCK-1",
                       "--dry-run", "--force", "--db", db, "--quiet"])
    check("--force 可覆盖锁", rc2 == EXIT_OK, f"rc={rc2}")


# --------------------------------------------------------------- JSON 输出
def test_json_output() -> None:
    section("JSON 输出（脚本可消费）")
    import io
    import json as _json
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = runner_main(["status", "--task-id", "T-1", "--project", "demo",
                          "--db", DB, "--json"])
    out = buf.getvalue()
    try:
        data = _json.loads(out)
        check("status --json 合法", rc == EXIT_OK and isinstance(data, dict),
              f"keys={list(data)[:5]}")
    except Exception as e:
        check("status --json 合法", False, f"{e} | {out[:80]}")

    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        rc2 = monitor_main(["--task-id", "T-1", "--project", "demo", "--db", DB, "--json"])
    try:
        d2 = _json.loads(buf2.getvalue())
        check("monitor --json 合法", rc2 == EXIT_OK and "health" in d2,
              f"keys={list(d2)[:5]}")
    except Exception as e:
        check("monitor --json 合法", False, str(e)[:60])


# --------------------------------------------------------------- Windows 兼容
def test_windows_compat() -> None:
    section("Windows 路径与编码兼容")

    # 中文路径 + 中文任务 ID
    cn_db = os.path.join(tempfile.mkdtemp(), "中文目录", "状态.db")
    os.makedirs(os.path.dirname(cn_db), exist_ok=True)
    rc = runner_main(["run", "--project", "中文项目", "--task-id", "任务-甲",
                      "--description", "修改中文文案", "--dry-run", "--db", cn_db, "--quiet"])
    check("中文路径/项目/任务", rc == EXIT_OK, f"rc={rc}")

    rc2 = runner_main(["status", "--task-id", "任务-甲", "--project", "中文项目",
                       "--db", cn_db, "--quiet"])
    check("中文任务 status", rc2 == EXIT_OK, f"rc={rc2}")

    # 反斜杠路径（Windows）—— 用唯一文件名，避免跨运行残留导致重复执行拦截
    import uuid
    win_db = os.path.join(tempfile.gettempdir(), f"cli_win_{uuid.uuid4().hex[:8]}.db").replace("/", "\\")
    rc3 = runner_main(["run", "--project", "demo", "--task-id", "W-1",
                       "--dry-run", "--db", win_db, "--quiet"])
    check("Windows 反斜杠路径", rc3 == EXIT_OK, f"rc={rc3}")


# --------------------------------------------------------------- 依赖（无第三方）
def test_no_third_party() -> None:
    """CLI 不为自身引入**新增**必需第三方依赖。

    判定口径：
      - 硬依赖（模块顶层、非 try 块内）→ 违规
      - 可选依赖（try/except 内，可降级）→ 允许
      - 项目既有依赖（PyYAML 已被 scripts/_config.py 使用）→ 允许
    """
    section("无新增必需第三方依赖")
    import ast

    LOCAL = {
        "models", "exceptions", "state_manager", "task_router", "monitor",
        "runner", "verifier", "retry", "notifier", "zentao_reporter",
        "jenkins_adapter", "cli", "cli_util",
    }
    # 项目既有依赖（非本次 CLI 引入）
    EXISTING = {"yaml"}

    def walk_try(node):
        """收集 try 块内的 import（可选依赖）。"""
        opt = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Try):
                for ch in ast.walk(n):
                    if isinstance(ch, ast.Import):
                        for a in ch.names:
                            opt.add(a.name.split(".")[0])
                    elif isinstance(ch, ast.ImportFrom) and ch.module:
                        opt.add(ch.module.split(".")[0])
        return opt

    hard = []
    for fn in ("cli.py", "cli_util.py"):
        src = open(os.path.join(_AM, fn), encoding="utf-8").read()
        tree = ast.parse(src)
        optional = walk_try(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    root = a.name.split(".")[0]
                    if (root not in sys.stdlib_module_names and root not in LOCAL
                            and root not in optional and root not in EXISTING):
                        hard.append(f"{fn}:{a.name}")
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                root = node.module.split(".")[0]
                if (root not in sys.stdlib_module_names and root not in LOCAL
                        and root not in optional and root not in EXISTING):
                    hard.append(f"{fn}:{node.module}")
    check("无新增必需第三方依赖", not hard, f"{hard[:3]}")

    # yaml 可降级验证：缺 yaml 时 load_config 仍返回默认
    import cli_util
    orig = sys.modules.get("yaml")
    sys.modules["yaml"] = None  # 模拟缺失
    try:
        cfg = cli_util.load_config(os.path.join(_AM, "NOPE.yaml"))
        check("缺 yaml 时配置降级为默认", "execution" in cfg and "monitor" in cfg)
    finally:
        if orig is not None:
            sys.modules["yaml"] = orig
        else:
            sys.modules.pop("yaml", None)


# --------------------------------------------------------------- 工具
def test_util() -> None:
    section("cli_util 工具")
    cfg = load_config()
    check("配置加载含 execution", "execution" in cfg)
    check("配置加载含 monitor", "monitor" in cfg)
    t = table([["a", "b"]], ["x", "y"])
    check("table 渲染", "x" in t and "y" in t)
    check("truncate 截断", len(truncate("x" * 100, 10)) == 10)
    check("truncate 短文本不截断", truncate("abc", 10) == "abc")


def test_all_checks_passed() -> None:
    """pytest 收集时校验 check() 结果（原 main() 只在脚本方式执行）。"""
    fails = [(n, d) for n, s, d in _results if s == FAIL]
    assert not fails, fails


# --------------------------------------------------------------- 主入口
def main() -> int:
    print("P11.1 CLI 测试")
    print("=" * 60)
    test_argparse()
    test_exit_codes()
    test_run()
    test_edge_cases()
    test_lock()
    test_json_output()
    test_windows_compat()
    test_no_third_party()
    test_util()

    print("\n" + "=" * 60)
    p = sum(1 for _, s, _ in _results if s == PASS)
    f = sum(1 for _, s, _ in _results if s == FAIL)
    print(f"结果: {p} PASS / {f} FAIL / 共 {len(_results)}")
    if f:
        print("\n失败项:")
        for n, s, d in _results:
            if s == FAIL:
                print(f"  ✗ {n} {d}")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
