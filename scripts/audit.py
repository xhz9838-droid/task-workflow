# -*- coding: utf-8 -*-
"""审计日志：向 execution/<task>/audit.jsonl 追加一行 JSON（不写任何凭据）。

用法（模块）：from audit import audit; audit("3413", "zentao.update", {...})
用法（CLI）：python -I scripts/audit.py 3413 <action> '<json-detail>'
"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def audit(task_id, action, detail=None):
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
    if len(sys.argv) < 3:
        print("usage: audit.py <task_id> <action> [json-detail]")
        sys.exit(2)
    detail = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    print(json.dumps(audit(sys.argv[1], sys.argv[2], detail), ensure_ascii=False))
