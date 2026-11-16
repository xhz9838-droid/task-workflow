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

SKILLS = os.path.expanduser("~/.claude/skills")
CONFIG = os.path.join(SKILLS, "zentao", "_shared", "config.json")
MANAGE = os.path.join(SKILLS, "zentao-tasks", "scripts", "manage_tasks.py")
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
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
