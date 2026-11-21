# -*- coding: utf-8 -*-
"""本地仓库识别与路径校验（任务 §五）。

职责：
  - 技术栈识别（标志文件）：Java/Maven/Gradle、Vue/React/Node、uni-app、Python、未知
  - 仓库校验（只读，8 项）：路径存在/是目录/Git 特征/Git 根一致/remote 一致/
    工作区可读/可访问/角色一致
  - BLOCKED 语义：路径缺失等环境问题 → blocked 明细，要求用户处理，不自动修复

安全红线（本模块绝不）：clone / checkout / 切分支 / 改 remote / 清理工作区 / push。
所有 Git 操作只读（rev-parse / remote get-url / status --porcelain）。
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

try:
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass


@dataclass(frozen=True)
class TechSignature:
    technology: str
    markers: tuple


# 识别顺序即优先级（uni-app 先于通用 node/vue：package.json 同在时看 manifest）
TECH_SIGNATURES: tuple = (
    TechSignature("uni-app", ("manifest.json", "uni.prompts.json", "uni_modules")),
    TechSignature("java-maven", ("pom.xml",)),
    TechSignature("java-gradle", ("build.gradle", "build.gradle.kts", "settings.gradle")),
    TechSignature("python", ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile")),
    TechSignature("vue", ("package.json",)),   # package.json 细分见 detect_technology
    TechSignature("react", ("package.json",)),
    TechSignature("node", ("package.json",)),
)


def detect_technology(path: str) -> str:
    """按标志文件识别技术栈。识别不出 → "unknown"（不猜测）。"""
    if not os.path.isdir(path):
        return "unknown"
    names = set(os.listdir(path))
    for sig in TECH_SIGNATURES:
        if any(m in names for m in sig.markers):
            if sig.technology in ("vue", "react", "node"):
                return _detect_node_stack(path, names)
            return sig.technology
    return "unknown"


def _detect_node_stack(path: str, names: set) -> str:
    """package.json 存在时细分 uni-app / vue / react / node。"""
    pkg = _read_json_dict(os.path.join(path, "package.json"))
    deps = {}
    deps.update(pkg.get("dependencies") or {})
    deps.update(pkg.get("devDependencies") or {})
    if "manifest.json" in names or "@dcloudio/uni-app" in deps or "@dcloudio/vite-plugin-uni" in deps:
        return "uni-app"
    if "vue" in deps:
        return "vue"
    if "react" in deps:
        return "react"
    return "node"


def _read_json_dict(path: str) -> dict:
    import json

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


# --------------------------------------------------------------- Git 只读
def _git(path: str, *args: str) -> tuple:
    """执行 git 只读命令 → (ok, stdout.strip(), stderr.strip())。"""
    try:
        p = subprocess.run(
            ["git", "-C", path, *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
        return p.returncode == 0, p.stdout.strip(), p.stderr.strip()
    except Exception as e:  # noqa: BLE001 —— 环境问题按 blocked 呈现，不抛
        return False, "", str(e)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(path))))


@dataclass
class RepoCheck:
    """单仓库校验结果。status: ok | blocked | mismatch。"""
    repo_key: str
    path: str
    role: str = ""
    technology: str = "unknown"
    status: str = "ok"
    problems: list = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def check_repo(
    repo_key: str,
    path: str,
    *,
    role: str = "",
    expect_role: str = "",
    expect_remote: str = "",
    require_git: bool = True,
) -> RepoCheck:
    """单仓库 8 项校验（§五）。缺路径/缺 Git → status=blocked；remote/根不一致 → mismatch。"""
    res = RepoCheck(repo_key=repo_key, path=path or "", role=role or expect_role)
    if not path:
        res.status = "blocked"
        res.problems.append("未配置本地路径（用户 project_paths 与项目 path 均缺）")
        return res
    if not os.path.exists(path):
        res.status = "blocked"
        res.problems.append("路径不存在：%s（请自行处理，系统不自动 clone/创建）" % path)
        return res
    if not os.path.isdir(path):
        res.status = "blocked"
        res.problems.append("路径不是目录：%s" % path)
        return res

    res.technology = detect_technology(path)

    ok, git_root, err = _git(path, "rev-parse", "--show-toplevel")
    if not ok:
        if require_git:
            res.status = "blocked"
            res.problems.append("不是 Git 仓库（或 git 不可用）：%s" % (err or path))
        res.details["git"] = False
        return res
    res.details["git"] = True
    res.details["git_root"] = git_root
    if _norm(git_root) != _norm(path):
        res.status = "mismatch"
        res.problems.append("Git 根目录与配置路径不一致：%s ≠ %s" % (git_root, path))

    if expect_remote:
        ok, remote, err = _git(path, "remote", "get-url", "origin")
        res.details["remote"] = remote if ok else ""
        if not ok:
            res.status = "blocked"
            res.problems.append("无法读取 git remote（%s）" % (err or "no origin"))
        else:
            if not _remote_equal(remote, expect_remote):
                res.status = "mismatch"
                res.problems.append("git remote 与注册信息不一致：%s ≠ %s" % (remote, expect_remote))

    ok, porcelain, err = _git(path, "status", "--porcelain")
    if ok:
        res.details["dirty"] = bool(porcelain)  # 仅记录（未提交文件不阻断，不清理）
    else:
        res.status = "blocked"
        res.problems.append("无法读取工作区状态（%s）" % (err or ""))

    if expect_role and role and role != expect_role:
        res.status = "mismatch"
        res.problems.append("仓库角色与项目配置不一致：%s ≠ %s" % (role, expect_role))

    return res


def _remote_equal(a: str, b: str) -> bool:
    """remote 地址归一比较（去尾部 .git、斜杠、大小写；scp 形式视为不同——不猜测）。"""
    def norm(u: str) -> str:
        u = (u or "").strip().rstrip("/")
        if u.endswith(".git"):
            u = u[:-4]
        return _norm(u) if "://" not in u else u.lower()
    return norm(a) == norm(b)


def check_project_repos(project_cfg: dict, repo_paths: dict, *, require_git: bool = True) -> list:
    """按项目配置逐仓库校验。repo_paths：{repo_key: 本地路径}（用户映射优先，已解析）。"""
    out = []
    for r in (project_cfg.get("repositories") or []):
        key = str(r.get("key") or "")
        if not key or r.get("enabled") is False:
            continue
        out.append(check_repo(
            key,
            (repo_paths or {}).get(key) or r.get("path") or "",
            expect_role=str(r.get("role") or ""),
            expect_remote=str(r.get("remote_url") or r.get("remote") or ""),
            require_git=require_git and bool(r.get("require_git", True)),
        ))
    return out


# --------------------------------------------------------------- CLI（独立可诊断）
def main(argv=None) -> int:
    """只读仓库校验 CLI：输出明确结果与退出码（0=全部 ok，1=有问题，2=用法错误）。"""
    import argparse
    import json
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)

    ap = argparse.ArgumentParser(prog="repo_check.py", description="项目仓库只读校验")
    ap.add_argument("--project", required=True)
    ap.add_argument("--user", default="", help="工作流 user_id（可选）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        from _config import load_config
        from project_resolver import build_context
        ctx = build_context(args.project, user_id=args.user or None)
        cfg = load_config(args.project, args.user or None, strict=True)
        results = check_project_repos(cfg.get("project") or {}, ctx.get("repo_paths") or {})
    except Exception as e:  # noqa: BLE001 —— CLI 必须给出退出码，不静默
        print("❌ %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 2

    payload = [{
        "repo": r.repo_key, "path": r.path, "role": r.role,
        "technology": r.technology, "status": r.status,
        "problems": r.problems, "details": r.details,
    } for r in results]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        for r in results:
            print("[%s] %s: %s %s" % (r.status.upper(), r.repo_key, r.path,
                                      ("；".join(r.problems) if r.problems else "")))
    return 0 if all(r.status == "ok" for r in results) else 1


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(main(_sys.argv[1:]))
