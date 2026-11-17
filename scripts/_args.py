# -*- coding: utf-8 -*-
"""调用参数解析（project_key / task_id）与任务→项目归属匹配。

规则（与 SKILL.md 一致）：
  - task_id：纯数字，允许 # 前缀；`#3415` 只表示任务号，不是完整参数
  - project_key：非数字标识（对应 config/projects/{project_key}.yaml）
  - 两者独立解析；project_key 缺失时不推断：先经禅道任务查询验证归属
    （match_project），能唯一确定才使用；否则询问用户

用法（模块）：
    from _args import parse_invocation, match_project
    parse_invocation(["#3415"])   # {"project_key": None, "task_id": "3415", "missing": ["project_key"]}

CLI：
    python -I scripts/_args.py parse <tokens...>
    python -I scripts/_args.py match-project --task-json <file|-> [--home <dir>]
        读禅道任务详情 JSON，扫描 <home>/config/projects/*.yaml，唯一命中打印 project_key；
        无法唯一确定 → 退出码 4（须询问用户）。
"""
from __future__ import annotations

import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_TASK_RE = re.compile(r"^\d+$")
_KEY_BAD_CHARS = " \t/\\:"


class ArgsError(Exception):
    """调用参数无法解析——必须人工澄清，不猜测。"""


def parse_invocation(tokens) -> dict:
    """解析调用参数 → {"project_key", "task_id", "missing"}。

    - `#3415` / `3415` → task_id="3415"，project_key 缺失（不推断）
    - `jeebootx 3415` / `jeebootx #3415` / `3415 jeebootx` → 两者齐备
    - 同类参数给两个、或出现 - 开头的选项 → ArgsError
    """
    project_key = None
    task_id = None
    for tok in tokens or []:
        tok = (tok or "").strip()
        if not tok:
            continue
        if tok.startswith("-"):
            raise ArgsError("不支持的选项 %r：参数只接受 {project_key} {task_id}" % tok)
        if tok.startswith("#"):
            tok = tok[1:]
        if not tok:
            continue
        if _TASK_RE.match(tok):
            if task_id is not None:
                raise ArgsError("给定了多个任务号：%s 与 %s" % (task_id, tok))
            task_id = tok
        else:
            if project_key is not None:
                raise ArgsError("给定了多个 project_key：%s 与 %s" % (project_key, tok))
            if any(c in tok for c in _KEY_BAD_CHARS):
                raise ArgsError("非法 project_key：%r" % tok)
            project_key = tok
    missing = []
    if project_key is None:
        missing.append("project_key")
    if task_id is None:
        missing.append("task_id")
    return {"project_key": project_key, "task_id": task_id, "missing": missing}


def match_project(task_detail: dict, projects: list):
    """按禅道任务详情匹配项目配置。唯一命中 → project_key；否则 None（须询问用户）。

    task_detail：禅道任务字段 dict（至少含 project，可含 projectName/projectTitle）
    projects：[{"key","name","zentao_project"?}, ...]（来自 config/projects/*.yaml 的 project:）
    匹配：任务的 project/projectName/projectTitle 任一值 ==
          配置的 key / name / zentao_project（标量或列表）任一值
    """
    if not task_detail or not projects:
        return None
    refs = set()
    for field in ("project", "projectName", "projectTitle"):
        v = task_detail.get(field)
        if v not in (None, ""):
            refs.add(str(v).strip())
    if not refs:
        return None
    hits = []
    for p in projects:
        key = str(p.get("key") or "").strip()
        if not key:
            continue
        cand = set()
        for field in ("key", "name", "zentao_project"):
            v = p.get(field)
            if isinstance(v, (list, tuple)):
                cand.update(str(x).strip() for x in v if x not in (None, ""))
            elif v not in (None, ""):
                cand.add(str(v).strip())
        if refs & cand and key not in hits:
            hits.append(key)
    return hits[0] if len(hits) == 1 else None


# --------------------------------------------------------------- CLI
def _load_projects(home: str) -> list:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _config import _read_yaml
    out = []
    pdir = os.path.join(home, "config", "projects")
    if not os.path.isdir(pdir):
        return out
    for fn in sorted(os.listdir(pdir)):
        if not fn.endswith((".yaml", ".yml", ".json")) or ".example." in fn:
            continue
        data = _read_yaml(os.path.join(pdir, fn))
        proj = data.get("project", data) if isinstance(data, dict) else {}
        if isinstance(proj, dict):
            out.append(proj)
    return out


def main(argv):
    args = list(argv[1:])
    if not args:
        print(__doc__)
        return 2
    cmd, rest = args[0], args[1:]
    try:
        if cmd == "parse":
            print(json.dumps(parse_invocation(rest), ensure_ascii=False))
            return 0
        if cmd == "match-project":
            task_file = None
            home = None
            if "--task-json" in rest:
                task_file = rest[rest.index("--task-json") + 1]
            if "--home" in rest:
                home = rest[rest.index("--home") + 1]
            if not task_file:
                print("❌ 缺少 --task-json <file|->", file=sys.stderr)
                return 2
            raw = sys.stdin.read() if task_file == "-" else open(task_file, encoding="utf-8").read()
            task = json.loads(raw)
            if not home:
                from _home import resolve_workflow_home
                home = resolve_workflow_home()[0]
            key = match_project(task, _load_projects(home))
            if key:
                print(key)
                return 0
            print("❌ 无法唯一确定任务 %s 的项目归属，请询问用户。" % task.get("id"), file=sys.stderr)
            return 4
    except ArgsError as e:
        print("❌ %s" % e, file=sys.stderr)
        return 3
    print("未知命令：%s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
