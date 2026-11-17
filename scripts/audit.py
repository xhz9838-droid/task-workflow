# -*- coding: utf-8 -*-
"""审计日志：向 execution/<task>/audit.jsonl 追加一行 JSON（不写任何凭据）。

用法（模块）：from audit import audit; audit("3413", "zentao.update", {...})
用法（CLI）：python -I scripts/audit.py 3413 <action> '<json-detail>'
"""
import datetime
import json
import os
import sys


def _root() -> str:
    """工作流根目录（统一解析，见 _home.py）；解析失败回退脚本所在仓库，审计不因定位问题丢记录。"""
    try:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from _home import resolve_workflow_home
        return resolve_workflow_home()[0]
    except Exception:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = _root()


def audit(task_id, action, detail=None, project_key=None):
    """审计日志。project_key 给定时写 execution/{project}/{task}/，否则回退旧扁平路径。"""
    if project_key:
        path = os.path.join(ROOT, "execution", str(project_key), str(task_id), "audit.jsonl")
    else:
        path = os.path.join(ROOT, "execution", str(task_id), "audit.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rec = {
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "task": str(task_id),
        "action": action,
        "detail": detail or {},
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


if __name__ == "__main__":
    # 用法：audit.py <task_id> <action> [json-detail] [--project <key>]
    argv = sys.argv[1:]
    proj = None
    if "--project" in argv:
        i = argv.index("--project")
        proj = argv[i + 1]
        del argv[i:i + 2]
    if len(argv) < 2:
        print("usage: audit.py <task_id> <action> [json-detail] [--project <key>]")
        sys.exit(2)
    detail = json.loads(argv[2]) if len(argv) > 2 else {}
    print(json.dumps(audit(argv[0], argv[1], detail, project_key=proj), ensure_ascii=False))
