# -*- coding: utf-8 -*-
"""统一项目解析（任务 §三.3）：项目注册表 + ZenTao 任务→project_key + 用户路径映射 + 项目上下文。

原则：
  - Skill / Agent / 各脚本一律经本模块解析项目，**不各自实现映射逻辑**
  - 核心匹配谓词复用 `scripts/_args.py match_project`（单项目探测复用），
    本模块只做**可靠性分级与唯一性裁决**（名称不得单独作为可靠依据）
  - 无法唯一确定 → 明确返回 ambiguous/unregistered，**不猜测项目**

CLI：
  python -I scripts/project_resolver.py match --task-json <file|-> [--user <id>] [--json]
  python -I scripts/project_resolver.py context --project <key> --user <id> [--json]
"""
from __future__ import annotations

import json
import os
import sys

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from _args import match_project  # noqa: E402  —— 核心匹配谓词单点复用
from _config import get, load_config  # noqa: E402
from _home import resolve_workflow_home  # noqa: E402


class ResolveError(Exception):
    """项目解析失败——须人工处理，不猜测。"""


# --------------------------------------------------------------- 注册表
def load_registry(home: str | None = None) -> list:
    """加载 config/projects/*.yaml 的 project 块（含 zentao 归属字段）。"""
    from _args import _load_projects  # noqa: PLC2701 —— 同仓私有加载器，复用不重写

    root = home or resolve_workflow_home()[0]
    return _load_projects(root)


# --------------------------------------------------------------- 可靠性分级
def classify_tier(task_detail: dict, project: dict) -> str:
    """命中强度：exact（项目 ID）> product（产品 ID）> text（仅名称/key 文本）> ""（未命中）。

    名称/key 文本命中不可单独作为可靠依据（任务 §四.2）。
    """
    t_refs = _task_refs(task_detail)
    p_exact = _project_id_refs(project)
    p_products = _product_refs(project)

    if t_refs["project_id"] and p_exact and t_refs["project_id"] in p_exact:
        return "exact"
    if t_refs["project_id"] and p_exact and t_refs["project_id"].isdigit() and (
        {x for x in p_exact if x.isdigit()} & {t_refs["project_id"]}
    ):
        return "exact"
    if t_refs["product_ids"] and p_products and (t_refs["product_ids"] & p_products):
        return "product"
    if match_project(task_detail, [project]):  # 谓词复用（key/name/zentao_project 文本交集）
        return "text"
    return ""


def _task_refs(task_detail: dict) -> dict:
    pid = str(task_detail.get("project") or "").strip()
    products = set()
    for v in (task_detail.get("product_ids"), task_detail.get("products"), task_detail.get("product")):
        if isinstance(v, (list, tuple, set)):
            products.update(str(x).strip() for x in v if x not in (None, ""))
        elif v not in (None, ""):
            products.add(str(v).strip())
    products.discard(pid)
    return {"project_id": pid, "product_ids": products}


def _project_id_refs(project: dict) -> set:
    """配置侧项目 ID 引用：project.zentao.project_id + zentao_project 中的数字项。"""
    out = set()
    zid = get(project, "zentao.project_id")
    if zid not in (None, ""):
        out.add(str(zid).strip())
    zp = project.get("zentao_project")
    for x in (zp if isinstance(zp, (list, tuple)) else [zp]):
        if x not in (None, ""):
            out.add(str(x).strip())
    return out


def _product_refs(project: dict) -> set:
    out = set()
    for x in (get(project, "zentao.product_ids") or []):
        if x not in (None, ""):
            out.add(str(x).strip())
    return out


# --------------------------------------------------------------- 解析
def match_hits(task_detail: dict, registry: list) -> list:
    """全部命中项 [(project, tier, key), ...]，按强度排序。"""
    hits = []
    for p in registry or []:
        tier = classify_tier(task_detail, p)
        if tier:
            hits.append((p, tier, str(p.get("key") or "")))
    order = {"exact": 0, "product": 1, "text": 2}
    hits.sort(key=lambda h: order.get(h[1], 9))
    return hits


def resolve_by_task(task_detail: dict, *, registry: list | None = None, user_id: str | None = None) -> dict:
    """禅道任务 → 项目解析裁决。

    返回 {status, project_key?, candidates, reason}：
      resolved        唯一可靠命中（exact / product）→ 直接可用
      needs_confirm   仅唯一 text 命中 → 名称辅助，须用户确认（不自动采用）
      ambiguous       多个候选 → 询问用户
      unregistered    无命中 → 提示注册（提供注册入口）
      disabled        唯一命中但项目已禁用
    """
    reg = registry if registry is not None else load_registry()
    enabled = [p for p in reg if p.get("enabled") is not False]
    disabled = [p for p in reg if p.get("enabled") is False]

    hits = match_hits(task_detail, enabled)
    if not hits:
        if match_hits(task_detail, disabled):
            return {"status": "disabled", "candidates": [], "reason": "匹配到的项目已在配置中禁用"}
        return {"status": "unregistered", "candidates": [],
                "reason": "禅道任务所属项目未注册：请先运行 /workflow-register-project"}

    top_tier = hits[0][1]
    top = [h for h in hits if h[1] == top_tier]
    cands = [{"project_key": h[2], "tier": h[1], "name": h[0].get("name", "")} for h in top]

    if len(top) == 1:
        if top_tier in ("exact", "product"):
            return {"status": "resolved", "project_key": top[0][2], "candidates": cands,
                    "reason": "唯一%s命中" % {"exact": "项目 ID", "product": "产品 ID"}[top_tier]}
        return {"status": "needs_confirm", "project_key": top[0][2], "candidates": cands,
                "reason": "仅名称辅助命中（不可单独作为可靠依据），请确认项目归属"}
    return {"status": "ambiguous", "candidates": cands,
            "reason": "存在 %d 个候选项目，请选择" % len(top)}


def resolve_by_key(project_key: str, *, user_id: str | None = None) -> dict:
    """显式 project_key → 项目上下文（缺失/禁用明确报错）。"""
    if not project_key:
        raise ResolveError("缺少 project_key")
    reg = load_registry()
    hit = next((p for p in reg if str(p.get("key") or "") == str(project_key)), None)
    if hit is None:
        raise ResolveError("项目配置不存在：%s（config/projects/%s.yaml）" % (project_key, project_key))
    if hit.get("enabled") is False:
        raise ResolveError("项目已禁用：%s（project.enabled: false）" % project_key)
    return build_context(project_key, user_id=user_id)


# --------------------------------------------------------------- 用户路径与上下文
def current_user_id(explicit: str | None = None) -> str:
    """当前用户解析：显式参数 > WORKFLOW_USER_ID 环境变量 > 用户级工作流配置。不猜测。"""
    return _resolve_user_id(explicit)[0]


def resolve_user_id_optional(explicit: str | None = None) -> tuple[str, str]:
    """当前用户解析（可选）：解析不到返回 ("", "unresolved: …")，不抛错。

    普通启动/项目上下文不需要 user_id；只有依赖用户路径映射或决策人身份的功能才需要。
    """
    try:
        return _resolve_user_id(explicit)
    except ResolveError as e:
        return "", "unresolved: %s" % e


def _resolve_user_id(explicit: str | None = None) -> tuple[str, str]:
    """当前用户解析，返回 (user_id, source)。

    source: "explicit" | "env:WORKFLOW_USER_ID" | "config:~/.claude/zentao-dev-workflow.json"
    """
    if explicit:
        return str(explicit).strip(), "explicit"
    env = (os.environ.get("WORKFLOW_USER_ID") or "").strip()
    if env:
        return env, "env:WORKFLOW_USER_ID"
    try:
        uc = os.path.expanduser("~/.claude/zentao-dev-workflow.json")
        if os.path.exists(uc):
            with open(uc, encoding="utf-8") as f:
                uid = str((json.load(f) or {}).get("user_id") or "").strip()
            if uid:
                return uid, "config:~/.claude/zentao-dev-workflow.json"
    except Exception:
        pass
    raise ResolveError(
        "无法确定当前用户：请显式传 user_id，或设置环境变量 WORKFLOW_USER_ID，"
        "或在 ~/.claude/zentao-dev-workflow.json 配置 user_id"
    )


def _user_id_source(explicit: str | None = None) -> str:
    """返回 user_id 的来源描述（用于 whoami 命令诊断）。"""
    try:
        _, source = _resolve_user_id(explicit)
        return source
    except ResolveError as e:
        return "unresolved: %s" % str(e)


def load_user_paths(user_id: str, home: str | None = None) -> dict:
    """读 config/users/{user_id}.yaml 的 project_paths（{project_key: {repo_key: path}}）。"""
    root = home or resolve_workflow_home()[0]
    path = os.path.join(root, "config", "users", "%s.yaml" % user_id)
    if not os.path.exists(path):
        return {}
    from _config import _read_yaml  # noqa: PLC2701 —— 复用加载器（YAML/JSON 回退）

    data = _read_yaml(path)
    pp = (data.get("user") or data).get("project_paths") if isinstance(data, dict) else {}
    out = {}
    for pk, repos in (pp or {}).items():
        if isinstance(repos, dict):
            out[str(pk)] = {str(k): os.path.expanduser(str(v)) for k, v in repos.items() if v}
    return out


def repo_paths_for(project_cfg: dict, user_id: str | None, *, home: str | None = None) -> dict:
    """{repo_key: 本地路径}：用户 project_paths 优先，回退项目配置 path（${ENV} 已展开）。"""
    paths = {}
    for r in (get(project_cfg, "project.repositories") or []):
        if r.get("key"):
            paths[str(r["key"])] = str(r.get("path") or "")
    if user_id:
        up = load_user_paths(user_id, home=home).get(str(get(project_cfg, "project.key")), {})
        for k, v in up.items():
            if v:
                paths[k] = v
    return paths


def build_context(project_key: str, *, user_id: str | None = None, home: str | None = None,
                  resolve_user: bool = True) -> dict:
    """统一项目上下文（所有 Agent 共用）。

    user_id 可选：解析不到时 context 仍可构建（user_id=""），
    用户级 project_paths 映射降级为项目配置 path；依赖用户身份的功能自行在调用点检查。
    resolve_user=False 表示不解析用户（降级重建上下文时用）。
    """
    uid, user_source = (resolve_user_id_optional(user_id) if resolve_user
                        else ("", "unresolved"))
    cfg = load_config(project_key=project_key, user_id=uid or None, strict=True)
    proj = get(cfg, "project") or {}
    repos = get(cfg, "project.repositories") or []
    return {
        "project_key": str(proj.get("key") or project_key),
        "project_name": str(proj.get("name") or ""),
        "user_id": uid,
        "user_source": user_source,
        "baseline_branch": str(proj.get("baseline_branch") or ""),
        "agents": [k for k, v in (proj.get("agents") or {}).items() if v is True],
        "integrations": proj.get("integrations") or {},
        "tech_stack": proj.get("tech_stack") or {},
        "repositories": [
            {"key": str(r.get("key")), "role": r.get("role", ""), "technology": r.get("technology", ""),
             "enabled": r.get("enabled", True)}
            for r in repos if r.get("key")
        ],
        "repo_paths": repo_paths_for(cfg, uid or None, home=home),
        "execution_root": os.path.join(
            get(cfg, "execution_root") or os.path.join(resolve_workflow_home()[0], "execution"),
            str(project_key),
        ),
    }


# --------------------------------------------------------------- CLI
def main(argv=None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="project_resolver", description="统一项目解析")
    sub = p.add_subparsers(dest="cmd")
    pm = sub.add_parser("match", help="禅道任务→项目解析")
    pm.add_argument("--task-json", required=True)
    pm.add_argument("--user", default="")
    pm.add_argument("--json", action="store_true")
    pc = sub.add_parser("context", help="项目上下文")
    pc.add_argument("--project", required=True)
    pc.add_argument("--user", default="")
    pc.add_argument("--json", action="store_true")
    pw = sub.add_parser("whoami", help="解析当前用户 ID（不依赖 OS 用户名）")
    pw.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "match":
        src = sys.stdin if args.task_json == "-" else open(args.task_json, encoding="utf-8")
        task = json.load(src)
        r = resolve_by_task(task, user_id=args.user or None)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return {"resolved": 0, "needs_confirm": 4}.get(r["status"], 4 if r["status"] != "resolved" else 0)
    if args.cmd == "context":
        try:
            ctx = build_context(args.project, user_id=args.user or None)
        except ResolveError as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
            return 3
        print(json.dumps(ctx, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "whoami":
        try:
            uid = current_user_id()
            print(json.dumps({"user_id": uid, "source": _user_id_source()}, ensure_ascii=False))
        except ResolveError as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
            return 3
        return 0
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
