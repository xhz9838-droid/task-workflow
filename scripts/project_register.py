# -*- coding: utf-8 -*-
"""项目注册 CLI（任务 §三.4）：查重 / 仓库校验 / 技术栈识别 / dry-run / 确认写入 / 注册报告。

两段式（确认环节不可跳过）：
  plan   —— 只读：查重 + 识别 + 校验，输出计划 JSON 与指纹（fingerprint），不写任何文件
  apply  —— 按计划写入：必须 --confirm <fingerprint>（与 plan 指纹一致才执行）；
            --dry-run 预览将写入的内容；失败不留半成品（临时文件原子替换）

写入范围（仅此两类，均原子写）：
  - config/projects/{key}.yaml        项目公共配置（不含个人绝对路径/凭据，可进 Git）
  - config/users/{user_id}.yaml       追加 project_paths（**只增不改**既有键；绝不覆盖既有配置）

安全红线：不 clone / 不改 Git / 不写禅道 / 不覆盖用户配置 / 校验失败不写半成品。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from _config import _read_yaml, get  # noqa: E402
from _home import resolve_workflow_home  # noqa: E402
from project_resolver import current_user_id, load_registry  # noqa: E402
from repo_check import check_repo, detect_technology  # noqa: E402

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class RegisterError(Exception):
    """注册校验失败——不写入任何文件。"""


def _try_resolve_user() -> str:
    """尝试从环境/配置解析当前用户；失败返回空字符串（`--user` 为可选参数）。"""
    try:
        return current_user_id()
    except Exception:
        return ""


# --------------------------------------------------------------- plan
def build_plan(*, project_key: str, name: str, zentao_project_id="", product_ids=None,
               repos=None, user_id="", agents=None, baseline_branch="main", home=None) -> dict:
    """只读生成注册计划。repos：{repo_key: {"path","role","remote_url"}}。"""
    root = home or resolve_workflow_home()[0]
    if not project_key or not _KEY_RE.match(project_key):
        raise RegisterError("非法 project_key：%r（只允许字母数字_-，且不以符号开头）" % project_key)
    if not name:
        raise RegisterError("缺少项目名称 --name")

    registry = load_registry(root)
    dup_key = [p.get("key") for p in registry if str(p.get("key") or "") == project_key]
    if dup_key:
        raise RegisterError("project_key 已存在：%s（如需更新请用 update 模式，不覆盖重建）" % project_key)

    zid = str(zentao_project_id or "").strip()
    if zid:
        for p in registry:
            refs = _zentao_refs(p)
            if zid in refs:
                raise RegisterError(
                    "禅道项目 %s 已注册到 %s（不允许多个项目映射同一禅道项目）"
                    % (zid, p.get("key"))
                )

    user = str(user_id or "").strip()
    repo_plans = []
    for key, spec in (repos or {}).items():
        path = os.path.expanduser(str(spec.get("path") or ""))
        remote = str(spec.get("remote_url") or "").strip()
        chk = check_repo(key, path, expect_role=str(spec.get("role") or ""), expect_remote=remote)
        tech = chk.technology or detect_technology(path)
        if chk.status == "blocked":
            raise RegisterError("仓库 %s 校验 BLOCKED：%s" % (key, "；".join(chk.problems)))
        repo_plans.append({
            "key": key, "role": str(spec.get("role") or ""), "technology": tech,
            "remote_url": remote, "path": path,
            "status": chk.status, "problems": chk.problems, "dirty": chk.details.get("dirty", False),
        })
    if not repo_plans:
        raise RegisterError("至少需要一个仓库 --repo <key>=<path>")

    project_block = {
        "key": project_key, "name": name,
        "baseline_branch": str(baseline_branch or "main"),
        "zentao": {"project_id": int(zid) if zid.isdigit() else zid, "product_ids": list(product_ids or [])},
        "repositories": [
            {"key": r["key"], "role": r["role"], "technology": r["technology"],
             "enabled": True, "remote_url": r["remote_url"] or ""}
            for r in repo_plans
        ],
        "tech_stack": _rollup_tech(repo_plans),
        "agents": agents or {"dw-architect": True, "dw-database": True, "dw-java-backend": True,
                             "dw-web-frontend": True, "dw-mobile-app": False, "dw-qa-engineer": True,
                             "dw-integration-reviewer": True},
        "integrations": {"task_source": "zentao" if zid else "none", "ci": "none", "notification": "none"},
    }
    user_paths = {project_key: {r["key"]: r["path"] for r in repo_plans}} if user else {}

    plan = {
        "home": root, "project_key": project_key, "user_id": user,
        "project_block": project_block,
        "user_paths": user_paths,
        "repositories": repo_plans,
        "zentao_project_id": zid,
        "writes": ["config/projects/%s.yaml" % project_key] +
                  (["config/users/%s.yaml" % user] if user else []),
    }
    plan["fingerprint"] = fingerprint_of(plan)
    return plan


def _zentao_refs(p: dict) -> set:
    out = set()
    zid = get(p, "zentao.project_id")
    if zid not in (None, ""):
        out.add(str(zid).strip())
    zp = p.get("zentao_project")
    for x in (zp if isinstance(zp, (list, tuple)) else [zp]):
        if x not in (None, ""):
            out.add(str(x).strip())
    return out


def _rollup_tech(repo_plans):
    m = {"backend": "Java", "frontend": "Vue", "mobile": "uni-app"}
    out = {}
    for r in repo_plans:
        if r["role"] in m:
            out[r["role"]] = r["technology"]
    return out


def fingerprint_of(plan: dict) -> str:
    body = json.dumps({k: v for k, v in plan.items() if k != "fingerprint"},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------- apply
def apply_plan(plan: dict, *, confirm: str, dry_run: bool = False, user_cfg_path: str = None) -> dict:
    """按计划写入。confirm 必须等于 plan.fingerprint；dry_run 只预览。"""
    if confirm != plan.get("fingerprint"):
        raise RegisterError(
            "确认指纹不匹配：plan=%s confirm=%s（请重新 plan 并用最新指纹确认）"
            % (plan.get("fingerprint"), confirm)
        )
    root = plan["home"]
    changes = []

    proj_path = os.path.join(root, "config", "projects", plan["project_key"] + ".yaml")
    if os.path.exists(proj_path):
        raise RegisterError("配置已存在，拒绝覆盖：%s" % proj_path)
    proj_doc = {"project": plan["project_block"]}
    changes.append({"file": proj_path, "action": "create", "content": proj_doc})

    if plan.get("user_id"):
        u_path = user_cfg_path or os.path.join(root, "config", "users", plan["user_id"] + ".yaml")
        merged, action = _merge_user_paths(u_path, plan["user_paths"])
        changes.append({"file": u_path, "action": action, "content": merged})

    if dry_run:
        return {"dry_run": True, "changes": changes}

    for c in changes:
        _atomic_write_yaml(c["file"], c["content"])
    return {"dry_run": False, "written": [c["file"] for c in changes]}


def _merge_user_paths(user_path: str, add: dict):
    """读-改-写：仅新增 project_paths 键；已存在的映射**不覆盖**（冲突即报错）。"""
    existing = _read_yaml(user_path) if os.path.exists(user_path) else {}
    user_blk = dict(existing.get("user") or existing)
    pp = dict(user_blk.get("project_paths") or {})
    for pk, repos in (add or {}).items():
        cur = dict(pp.get(pk) or {})
        for rk, path in (repos or {}).items():
            if rk in cur and cur[rk] and str(cur[rk]) != str(path):
                raise RegisterError(
                    "用户 %s 已有路径映射 %s/%s = %s，拒绝覆盖为 %s"
                    % (user_path, pk, rk, cur[rk], path)
                )
            cur[rk] = path
        pp[pk] = cur
    user_blk["project_paths"] = pp
    out = dict(existing)
    if "user" in existing or not existing:
        out["user"] = user_blk
    else:
        out.update(user_blk)
    return out, ("update" if existing else "create")


def _atomic_write_yaml(path: str, content: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            try:
                import yaml  # type: ignore

                yaml.safe_dump(content, f, allow_unicode=True, sort_keys=False)
            except ImportError:
                json.dump(content, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# --------------------------------------------------------------- CLI
def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="project_register", description="项目注册（plan/apply 两段式）")
    sub = p.add_subparsers(dest="cmd")

    pp = sub.add_parser("plan", help="生成注册计划（只读）")
    pp.add_argument("--project-key", required=True)
    pp.add_argument("--name", required=True)
    pp.add_argument("--zentao-project-id", default="")
    pp.add_argument("--product-ids", default="")
    pp.add_argument("--repo", action="append", default=[],
                    help="key=path 或 key=path:role:remote_url（可多个）")
    pp.add_argument("--user", default="")
    pp.add_argument("--out", default="", help="计划 JSON 输出路径（默认打印）")

    pa = sub.add_parser("apply", help="按计划写入（需 --confirm 指纹）")
    pa.add_argument("--plan", required=True, help="plan 生成的 JSON 文件")
    pa.add_argument("--confirm", required=True, help="plan 输出的指纹")
    pa.add_argument("--dry-run", action="store_true")

    args = p.parse_args(argv)
    try:
        if args.cmd == "plan":
            repos = {}
            for item in args.repo:
                key, _, rest = item.partition("=")
                path, _, tail = rest.partition(":")
                role, _, remote = tail.partition(":")
                repos[key.strip()] = {"path": path.strip(), "role": role.strip(), "remote_url": remote.strip()}
            plan = build_plan(
                project_key=args.project_key, name=args.name,
                zentao_project_id=args.zentao_project_id,
                product_ids=[x for x in args.product_ids.split(",") if x],
                repos=repos, user_id=args.user or _try_resolve_user(),
            )
            body = json.dumps(plan, ensure_ascii=False, indent=2)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as f:
                    f.write(body)
            print(body)
            return 0
        if args.cmd == "apply":
            with open(args.plan, encoding="utf-8") as f:
                plan = json.load(f)
            result = apply_plan(plan, confirm=args.confirm, dry_run=args.dry_run)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        p.print_help()
        return 2
    except RegisterError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
