# -*- coding: utf-8 -*-
"""禅道薄封装：复用 ~/.claude/skills 的 ZenTaoClient 与 zentao-tasks/manage_tasks.py，不另写客户端。

子命令：
  detail   --task 3413                 只读：任务详情（仅本人任务）
  progress --task 3413 --stage <key> --text <内容>
           追加阶段进度到 desc 末尾（保留原文）；同一 stage 标记已存在则跳过（幂等）。
           写入走 manage_tasks.py update（统一 PUT + 读回核验）。

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


def cmd_worklog(args):
    """记工时（新增工作日志：日期/耗时/工作内容）。

    走 MVC 端点 task-recordWorkhour-<id>.html（Token 头认证，实证方式同 VERIFIED_WRITE）。
    注意：禅道 REST 无工时日志端点（实测 404），只能走此 MVC 端点；该端点受迭代 ACL
    约束，账号无迭代权限时返回『您无权访问该迭代』（如实报错，不谎报成功）。
    consumed 必须由人显式提供——PRD 5.5 禁止猜填工时。
    """
    import urllib.parse
    import urllib.request
    import urllib.error

    client = _client()
    task = _load_own_task(client, args.task)
    before = str(task.get("consumed") or "0")
    tok = client._token
    url = "%s/task-recordWorkhour-%s.html" % (client.base_url.rstrip("/"), args.task)
    fields = {"date": args.date, "consumed": str(args.consumed), "work": args.work}
    if args.left:
        fields["left"] = str(args.left)
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Token": tok,
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        html = e.read().decode("utf-8", "replace")
        print("❌ HTTP %s: %s" % (e.code, html[:300]))
        return 3
    if "无权访问" in html:
        print("❌ 记工时被拦截：『您无权访问该迭代』——账号缺迭代/项目权限（解决后重试即可）")
        return 2
    # 读回核验：任务 consumed 变化 + 页面回执特征
    after_task = client.task_detail(args.task)
    after = str(after_task.get("consumed") or "0")
    ok = after != before
    print("读回核验：consumed %s -> %s %s" % (before, after, "✅" if ok else "⚠️ 未变化"))
    if not ok:
        print("页面回执（前 200 字）：", html[:200])
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
    w = sub.add_parser("worklog", help="记工时：新增工作日志（日期/耗时/工作内容）")
    w.add_argument("--task", required=True)
    w.add_argument("--date", required=True, help="日期，如 2026-11-17")
    w.add_argument("--consumed", required=True, type=float, help="本日消耗（小时）——人工提供，禁止猜填")
    w.add_argument("--work", required=True, help="工作内容（已完成内容写这里，非 desc）")
    w.add_argument("--left", type=float, default=None, help="预计剩余（小时，可选）")
    w.set_defaults(func=cmd_worklog)
    j = sub.add_parser("projects", help="只读：当前用户可访问的禅道项目列表")
    j.set_defaults(func=cmd_projects)
    k = sub.add_parser("project", help="只读：任务→项目归属信息")
    k.add_argument("--task", required=True)
    k.set_defaults(func=cmd_project)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
