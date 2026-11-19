# -*- coding: utf-8 -*-
"""禅道薄封装：复用 ~/.claude/skills 的 ZenTaoClient 与 zentao-tasks/manage_tasks.py，不另写客户端。

子命令：
  detail   --task 3413                 只读：任务详情（仅本人任务）
  progress --task 3413 --stage <key> --text <内容>
           追加阶段进度到 desc 末尾（保留原文）；同一 stage 标记已存在则跳过（幂等）。
           写入走 manage_tasks.py update（统一 PUT + 读回核验）。
  finish   --task 3413 --consumed 8 --left 0 --finishedDate YYYY-MM-DD [--realStarted YYYY-MM-DD]
           完成任务 doing→done（复用 ZenTaoClient.task_finish 动作端点 + 读回核验）。
           幂等：已 done 直接跳过；受配置 zentao.allow_finish 控制（默认 auto_after_gate）。
  close    --task 3413 --comment <关闭备注>
           关闭任务 done→closed（关闭条件满足后自动执行 + 读回核验）。
           幂等：已 closed 直接跳过；受配置 zentao.allow_close 控制（默认 auto_after_gate）。
           finish 与 close 是两个独立的状态流转，均记录前后状态/结果/失败原因（audit.jsonl）。

调用：python -I scripts/zt.py <cmd> ...
"""
import argparse
import datetime
import html
import json
import os
import subprocess
import sys

# ZenTao 适配器路径：优先 config/adapters/zentao.yaml / 环境变量，回退用户级 Skill 默认位置。
# 不写死用户名与项目；凭据仅在 skill 级 config.json（gitignored），不进日志。
SKILLS = os.path.expanduser(os.environ.get("ZENTAO_SKILL_DIR") or "~/.claude/skills")
CONFIG = os.environ.get("ZENTAO_CONFIG") or os.path.join(SKILLS, "zentao", "_shared", "config.json")
MANAGE = os.environ.get("ZENTAO_MANAGE") or os.path.join(SKILLS, "zentao-tasks", "scripts", "manage_tasks.py")
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _config import load_config as _lc, get as _g
    _ad = _g(_lc(), "zentao", {}) or {}
    SKILLS = _ad.get("skill_dir") or SKILLS
    CONFIG = _ad.get("config_path") or CONFIG
    MANAGE = _ad.get("manage_script") or MANAGE
except Exception:
    pass
sys.path.insert(0, SKILLS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zentao._shared.client_api import ZenTaoClient, load_config  # noqa: E402
from zentao._shared.user_resolver import extract_account  # noqa: E402
from audit import audit  # noqa: E402

FIELDS = ("id", "name", "status", "pri", "type", "project", "execution", "executionName",
          "story", "storyTitle", "module", "estimate", "consumed", "left", "estStarted",
          "deadline", "realStarted", "finishedDate", "openedBy", "openedDate", "assignedTo", "desc")


def _client():
    cfg, path = load_config(CONFIG)
    return ZenTaoClient(cfg, config_path=path)


def _load_own_task(client, task_id):
    """读取任务并校验归属本人；不属于本人则抛错（禁止操作他人任务）。"""
    me = (client.whoami() or {}).get("profile", {}).get("account")
    task = client.task_detail(task_id)
    owner = extract_account(task.get("assignedTo"))
    if not me or owner != me:
        raise SystemExit("任务 %s 指派给 %r，当前账号 %r：非本人任务，拒绝操作" % (task_id, owner, me))
    return task


def _marker(task_id, stage):
    return "[AI-%s-%s]" % (task_id, stage)


def cmd_detail(args):
    task = _load_own_task(_client(), args.task)
    out = {k: task.get(k) for k in FIELDS if k in task}
    for k in ("assignedTo", "openedBy"):
        if k in out:
            out[k] = extract_account(out[k])
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


def cmd_progress(args):
    client = _client()
    task = _load_own_task(client, args.task)
    old = task.get("desc") or ""
    marker = _marker(args.task, args.stage)
    if marker in old:
        print("已存在 %s，跳过（幂等）" % marker)
        return 0
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    block = "<p>%s %s %s</p>" % (html.escape(marker), now, html.escape(args.text).replace("\n", "<br/>"))
    new = old + block
    cmd = [sys.executable, "-I", MANAGE, "--config", CONFIG, "update",
           "--task", str(args.task), "--fields", json.dumps({"desc": new}, ensure_ascii=False), "--yes"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)
    # 读回核验：以标记是否出现在 desc 且原文未丢失为准（禅道可能规范化 HTML，逐字比较不可靠）。
    after = client.task_detail(args.task).get("desc") or ""
    ok = marker in after and len(after) >= len(old)
    audit(args.task, "zentao.progress", {"stage": args.stage, "rc": proc.returncode, "verified": ok})
    print(proc.stdout[-1500:])
    if proc.returncode not in (0, 3):
        print(proc.stderr[-1500:])
    print(("✅" if ok else "❌") + " 读回核验：标记 %s %s" % (marker, "已写入" if ok else "未找到"))
    return 0 if ok else 3


def _allow_mode(path: str) -> str:
    """读取配置 zentao.allow_finish / zentao.allow_close（配置真正参与运行时决策）。

    - auto_after_gate（默认）：满足前置条件后自动执行
    - manual_only：收紧为本人手动（可选项，非默认）
    """
    try:
        from _config import load_config as _lc2, get as _g2
        v = _g2(_lc2(), path, None)
    except Exception:
        v = None
    return str(v or "auto_after_gate").strip().lower()


def cmd_finish(args):
    """完成任务 doing→done。复用 ZenTaoClient.task_finish + 读回核验。

    - 幂等：已 done 跳过，不重复流转
    - 工时/日期由调用方提供（consumed/left/finishedDate 必填），不推算
    - close 由 cmd_close 按关闭条件另行执行（finish 与 close 是两个独立流转）
    - 记录：任务 ID、执行 ID、操作前后状态、结果、失败原因写 audit.jsonl
    """
    mode = _allow_mode("zentao.allow_finish")
    if mode != "auto_after_gate":
        audit(args.task, "zentao.finish", {"result": "blocked_by_config", "mode": mode})
        print("配置 zentao.allow_finish=%s：拒绝自动 finish，需本人手动完成任务" % mode)
        return 3
    client = _client()
    task = _load_own_task(client, args.task)
    before = str(task.get("status") or "").lower()
    if before == "done":
        print("任务 %s 已是 done，跳过（幂等）" % args.task)
        audit(args.task, "zentao.finish", {"result": "skipped_already_done",
                                          "exec_id": args.exec_id, "before": before})
        return 0
    if before != "doing":
        audit(args.task, "zentao.finish", {"result": "deferred", "exec_id": args.exec_id,
                                          "before": before, "reason": "非 doing 状态，不猜测流转"})
        print("任务 %s 当前状态 %r 不是 doing，不允许 finish（doing→done），不猜测流转" % (args.task, before))
        return 3
    try:
        client.task_finish(
            args.task, args.consumed, args.left, args.finishedDate,
            realStarted=args.realStarted or None,
        )
    except Exception as e:
        audit(args.task, "zentao.finish", {"result": "failed", "exec_id": args.exec_id,
                                          "before": before, "error": str(e)[:200]})
        print("finish 调用失败：%s" % e)
        return 3
    # 读回核验：必须确认 status 已变 done
    try:
        after = str(client.task_detail(args.task).get("status") or "").lower()
    except Exception as e:
        audit(args.task, "zentao.finish", {"result": "readback_failed", "exec_id": args.exec_id,
                                          "before": before, "error": str(e)[:200]})
        print("finish 已调用但读回失败：%s" % e)
        return 4
    ok = after == "done"
    audit(args.task, "zentao.finish", {"result": "success" if ok else "readback_mismatch",
                                      "exec_id": args.exec_id,
                                      "before": before, "after": after, "verified": ok})
    print(("✅" if ok else "❌") + " 读回核验：status=%s（期望 done）" % after)
    return 0 if ok else 3


def cmd_close(args):
    """关闭任务 done→closed（关闭条件满足后自动执行）+ 读回核验。

    关闭条件：禅道状态须 done（交付/验收条件由上层判定）。不满足则暂缓并记录原因。幂等：已 closed 跳过。
    """
    mode = _allow_mode("zentao.allow_close")
    if mode != "auto_after_gate":
        audit(args.task, "zentao.close", {"result": "blocked_by_config", "mode": mode})
        print("配置 zentao.allow_close=%s：拒绝自动 close，需本人手动关闭" % mode)
        return 3
    client = _client()
    task = _load_own_task(client, args.task)
    before = str(task.get("status") or "").lower()
    if before == "closed":
        print("任务 %s 已是 closed，跳过（幂等）" % args.task)
        audit(args.task, "zentao.close", {"result": "skipped_already_closed",
                                         "exec_id": args.exec_id, "before": before})
        return 0
    if before != "done":
        audit(args.task, "zentao.close", {"result": "deferred", "exec_id": args.exec_id,
                                         "before": before, "reason": "仅 done→closed，当前状态不满足关闭条件"})
        print("暂缓关闭：任务 %s 当前状态 %r 不是 done（close 仅 done→closed）" % (args.task, before))
        return 3
    try:
        client.task_close(args.task, args.comment)
    except Exception as e:
        audit(args.task, "zentao.close", {"result": "failed", "exec_id": args.exec_id,
                                         "before": before, "error": str(e)[:200]})
        print("close 调用失败：%s" % e)
        return 3
    # 读回核验：必须确认 status 已变 closed
    try:
        after = str(client.task_detail(args.task).get("status") or "").lower()
    except Exception as e:
        audit(args.task, "zentao.close", {"result": "readback_failed", "exec_id": args.exec_id,
                                         "before": before, "error": str(e)[:200]})
        print("close 已调用但读回失败：%s" % e)
        return 4
    ok = after == "closed"
    audit(args.task, "zentao.close", {"result": "success" if ok else "readback_mismatch",
                                     "exec_id": args.exec_id,
                                     "before": before, "after": after, "verified": ok})
    print(("✅" if ok else "❌") + " 读回核验：status=%s（期望 closed）" % after)
    return 0 if ok else 3


def cmd_projects(args):
    """只读：当前用户可访问的禅道项目列表（项目注册第 1 步）。"""
    client = _client()
    data, _ = client._request(client.api_prefix + "/projects", method="GET", headers=client._auth_headers())
    items = (data or {}).get("projects") or []
    out = [{"id": it.get("id"), "name": it.get("name"), "status": it.get("status"), "type": it.get("type")}
           for it in items]
    print(json.dumps({"count": len(out), "projects": out}, ensure_ascii=False, indent=1))
    return 0


def cmd_project(args):
    """只读：任务→项目归属信息（项目自动发现输入）。仅本人任务。"""
    client = _client()
    task = _load_own_task(client, args.task)
    pid = str(task.get("project") or "").strip()
    name = ""
    try:
        data, _ = client._request(client.api_prefix + "/projects", method="GET", headers=client._auth_headers())
        for it in (data or {}).get("projects") or []:
            if str(it.get("id")) == pid:
                name = str(it.get("name") or "")
                break
    except Exception:
        pass  # 项目名称仅辅助识别，查不到不阻断
    products = set()
    for v in (task.get("product"), task.get("products"), task.get("product_id")):
        if isinstance(v, (list, tuple)):
            products.update(str(x).strip() for x in v if x not in (None, ""))
        elif v not in (None, ""):
            products.add(str(v).strip())
    out = {
        "task_id": task.get("id"), "task_name": task.get("name"), "task_status": task.get("status"),
        "project": pid, "projectName": name, "execution": task.get("execution"),
        "product_ids": sorted(products), "assignee": extract_account(task.get("assignedTo")),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detail")
    d.add_argument("--task", required=True)
    d.set_defaults(func=cmd_detail)
    g = sub.add_parser("progress")
    g.add_argument("--task", required=True)
    g.add_argument("--stage", required=True, help="阶段键，如 design / backend / jenkins-1")
    g.add_argument("--text", required=True)
    g.set_defaults(func=cmd_progress)
    f = sub.add_parser("finish", help="完成任务 doing→done（满足门禁后自动执行，读回核验）")
    f.add_argument("--task", required=True)
    f.add_argument("--consumed", type=float, required=True, help="已消耗工时（调用方提供，不推算）")
    f.add_argument("--left", type=float, required=True, help="剩余工时（调用方提供，不推算）")
    f.add_argument("--finishedDate", required=True, help="实际完成日期 YYYY-MM-DD")
    f.add_argument("--realStarted", help="实际开始日期 YYYY-MM-DD（doing 态 realStarted 为空时回填）")
    f.add_argument("--exec-id", default="", help="执行 ID（审计记录用）")
    f.set_defaults(func=cmd_finish)
    c = sub.add_parser("close", help="关闭任务 done→closed（关闭条件满足后自动执行，读回核验）")
    c.add_argument("--task", required=True)
    c.add_argument("--comment", required=True, help="关闭备注（禅道必填，不带则静默不生效）")
    c.add_argument("--exec-id", default="", help="执行 ID（审计记录用）")
    c.set_defaults(func=cmd_close)
    j = sub.add_parser("projects", help="只读：当前用户可访问的禅道项目列表")
    j.set_defaults(func=cmd_projects)
    k = sub.add_parser("project", help="只读：任务→项目归属信息")
    k.add_argument("--task", required=True)
    k.set_defaults(func=cmd_project)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
