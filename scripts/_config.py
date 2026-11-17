# -*- coding: utf-8 -*-
"""配置加载器：统一读取 workflow / adapters / projects / users 配置，供四个适配器脚本复用。

设计（见 execution/upgrade/02-architecture.md）：
- 加载顺序（后者覆盖前者）：内置默认 → workflow.yaml → adapters/*.yaml →
  projects/{key}.yaml → users/{id}.yaml → .env（仅覆盖敏感项）
- 配置中 ${VAR} 从 .env / 进程环境变量替换；未定义 → 明确报错，不猜测
- 优先 PyYAML；缺失时回退 JSON（同名 .json），并提示 pip install pyyaml

用法：
    from _config import load_config, resolve_repo, exec_root
    cfg = load_config(project_key="jeebootx", user_id="alice")
    path = resolve_repo(cfg, "backend")

CLI：
    python -I scripts/_config.py show <project_key> [<user_id>]
    python -I scripts/_config.py validate <project_key> [<user_id>]
"""
from __future__ import annotations

import json
import os
import re
import sys

# Windows 控制台可能是 GBK，统一强制 UTF-8 输出，避免 emoji/中文抛 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
from _home import resolve_workflow_home  # noqa: E402

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_root_cache = None


def workflow_root() -> str:
    """工作流根目录（统一解析，见 _home.py：env → 用户级配置 → 安装记录/开发源 → 向上探测）。"""
    global _root_cache
    if _root_cache is None:
        _root_cache = resolve_workflow_home()[0]
    return _root_cache


def config_dir() -> str:
    return os.path.join(workflow_root(), "config")


class ConfigError(Exception):
    """配置缺失或非法——必须人工处理，不猜测。"""


def _norm_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(path))))


# --------------------------------------------------------------- 读取
def _read_yaml(path: str):
    """读 YAML；PyYAML 缺失时回退同名 .json。"""
    if not os.path.exists(path):
        alt = re.sub(r"\.ya?ml$", ".json", path)
        if os.path.exists(alt):
            path = alt
        else:
            return {}
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    try:
        import yaml  # type: ignore
    except ImportError:
        raise ConfigError(
            "缺少 PyYAML，无法读取 %s。\n"
            "请执行：pip install pyyaml\n"
            "或将配置另存为同名 .json 文件。" % path
        )
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _read_env(path: str = None) -> dict:
    """读 .env（KEY=VALUE），不覆盖已有进程环境变量。"""
    path = path or os.path.join(workflow_root(), ".env")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            # 防御：.env 末尾缺换行会把下一个 KEY=VALUE 拼进上一行，这里截断掉
            if "\n" in v:
                v = v.split("\n")[0]
            key = k.strip()
            if not key or not key.replace("_", "").isalnum():
                continue
            out[key] = v.strip()
    return out


def _substitute(value, env: dict, path_hint: str = ""):
    """递归替换 ${VAR}。未定义变量 → 报错，不猜测。"""
    if isinstance(value, str):
        def rep(m):
            name = m.group(1)
            if name in env:
                return env[name]
            if name in os.environ:
                return os.environ[name]
            raise ConfigError(
                "配置 %s 中的环境变量 ${%s} 未定义。请在 .env 或系统环境变量中定义。"
                % (path_hint or "config", name)
            )
        return _VAR_RE.sub(rep, value)
    if isinstance(value, dict):
        return {k: _substitute(v, env, path_hint) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, env, path_hint) for v in value]
    return value


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# --------------------------------------------------------------- 加载
def load_config(project_key: str = None, user_id: str = None, *, strict: bool = True) -> dict:
    """按顺序合并配置。strict=True 时 project_key/user_id 必须存在。"""
    root = workflow_root()
    env = _read_env(os.path.join(root, ".env"))
    env_full = dict(os.environ)
    env_full.update(env)

    # WORKFLOW_HOME 统一以 _home.py 解析结果为准；.env 声明了不同值 → 配置冲突，明确报错
    declared = (env.get("WORKFLOW_HOME") or "").strip()
    if declared:
        if _norm_path(declared) != _norm_path(root):
            raise ConfigError(
                "WORKFLOW_HOME 冲突：.env 声明 %s，但解析结果为 %s。\n"
                "请修正 .env 或环境变量，避免状态目录分裂。" % (declared, root)
            )
    env_full["WORKFLOW_HOME"] = root

    merged = {"_env": env, "_root": root}

    # 1) 全局
    wf = _read_yaml(os.path.join(config_dir(), "workflow.yaml"))
    merged = _deep_merge(merged, wf)

    # 2) 适配器
    # 只加载实际配置（非 .example），example 模板含 ${占位符} 供参考，不当真配置加载。
    # 加载顺序：先实际 .yaml，同名 .example 被自然忽略（实际文件优先）。
    adapters_dir = os.path.join(config_dir(), "adapters")
    if os.path.isdir(adapters_dir):
        for fn in sorted(os.listdir(adapters_dir)):
            if fn.endswith((".yaml", ".yml", ".json")) and ".example" not in fn:
                name = os.path.splitext(fn)[0]
                data = _read_yaml(os.path.join(adapters_dir, fn))
                merged = _deep_merge(merged, {name: data.get(name, data)})

    # 3) 项目
    if project_key:
        p_path = os.path.join(config_dir(), "projects", project_key + ".yaml")
        if not os.path.exists(p_path) and not os.path.exists(re.sub(r"\.yaml$", ".json", p_path)):
            if strict:
                raise ConfigError(
                    "项目配置不存在：%s\n"
                    "请复制 config/projects/project.example.yaml 为 %s.yaml 并填写实际值。"
                    % (p_path, project_key)
                )
        else:
            _pd = _read_yaml(p_path)
            # YAML 顶层已含 project: 键则直接合并，否则包一层
            merged = _deep_merge(merged, _pd if "project" in _pd else {"project": _pd})

    # 4) 人员
    if user_id:
        u_path = os.path.join(config_dir(), "users", user_id + ".yaml")
        if not os.path.exists(u_path) and not os.path.exists(re.sub(r"\.yaml$", ".json", u_path)):
            if strict:
                raise ConfigError(
                    "人员配置不存在：%s\n"
                    "请复制 config/users/user.example.yaml 为 %s.yaml 并填写实际值。"
                    % (u_path, user_id)
                )
        else:
            _ud = _read_yaml(u_path)
            merged = _deep_merge(merged, _ud if "user" in _ud else {"user": _ud})

    # 5) 环境变量替换
    merged = _substitute(merged, env_full, "config")
    return merged


# --------------------------------------------------------------- 取值
def require(cfg: dict, path: str, hint: str = "") -> object:
    """按点路径取值，缺失则报错。如 require(cfg, "project.root")。"""
    node = cfg
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node or node[part] in (None, "", []):
            raise ConfigError("配置项缺失：%s%s" % (path, (" — " + hint) if hint else ""))
        node = node[part]
    return node


def get(cfg: dict, path: str, default=None):
    node = cfg
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return default if node is None else node


def resolve_repo(cfg: dict, repo_key: str) -> str:
    """仓库绝对路径。"""
    for r in get(cfg, "project.repositories", []) or []:
        if r.get("key") == repo_key:
            p = r.get("path")
            if not p:
                raise ConfigError("项目 %s 的仓库 %s 未配置 path" % (get(cfg, "project.key"), repo_key))
            return os.path.normpath(p)
    raise ConfigError(
        "项目 %s 无仓库 %s。可用：%s"
        % (get(cfg, "project.key"), repo_key, [r.get("key") for r in get(cfg, "project.repositories", []) or []])
    )


def exec_root(cfg: dict, project_key: str, task_id: str) -> str:
    """任务执行状态根目录 execution/{project_key}/{task_id}。"""
    base = get(cfg, "execution_root", os.path.join(workflow_root(), "execution"))
    return os.path.normpath(os.path.join(base, str(project_key), str(task_id)))


def worktree_root(cfg: dict) -> str:
    base = get(cfg, "worktree_root", os.path.join(workflow_root(), "..", ".worktrees"))
    return os.path.normpath(base)


def enabled_agents(cfg: dict) -> list:
    """项目启用的 Agent 名单（按 agents{} 为 true 的键）。"""
    ag = get(cfg, "project.agents", {}) or {}
    return [k for k, v in ag.items() if v is True]


def integration_enabled(cfg: dict, name: str) -> bool:
    v = get(cfg, "project.integrations.%s" % name, "none")
    return bool(v) and v != "none"


def adapter_enabled(cfg: dict, name: str) -> bool:
    return bool(get(cfg, "%s.enabled" % name, False))


# --------------------------------------------------------------- CLI
def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd, project_key = argv[1], argv[2]
    user_id = argv[3] if len(argv) > 3 else None
    try:
        cfg = load_config(project_key, user_id, strict=(cmd == "validate"))
    except ConfigError as e:
        print("❌ 配置错误：%s" % e)
        return 3
    if cmd == "show":
        safe = {k: v for k, v in cfg.items() if not k.startswith("_")}
        # 脱敏
        for sens in ("token", "password", "secret", "key"):
            if sens in json.dumps(safe, default=str).lower():
                break
        print(json.dumps(safe, ensure_ascii=False, indent=1, default=str))
        return 0
    if cmd == "validate":
        errs = []
        pk = get(cfg, "project.key")
        if pk != project_key:
            errs.append("project.key(%s) 与文件名(%s) 不一致" % (pk, project_key))
        for r in get(cfg, "project.repositories", []) or []:
            p = r.get("path")
            if not p:
                errs.append("仓库 %s 缺 path" % r.get("key"))
            elif not os.path.isdir(p):
                errs.append("仓库 %s 路径不存在：%s" % (r.get("key"), p))
        for a in enabled_agents(cfg):
            f = os.path.join(workflow_root(), ".claude", "agents", a + ".md")
            if not os.path.exists(f):
                errs.append("启用的 Agent 缺定义：%s" % a)
        # 集成名 → 适配器配置键（integrations 的值是供应商名，适配器键是集成名）
        _ad_name = {"task_source": "zentao", "ci": "jenkins", "notification": "notification"}
        for i in ("task_source", "ci", "notification"):
            if integration_enabled(cfg, i):
                provider = get(cfg, "project.integrations.%s" % i)
                ad = _ad_name.get(i, i)
                if not adapter_enabled(cfg, ad):
                    errs.append("集成 %s=%s 但适配器 %s.enabled 未开启" % (i, provider, ad))
        if errs:
            print("❌ 校验失败：")
            for e in errs:
                print("   - " + e)
            return 3
        print("✅ 项目 %s 配置校验通过（启用 Agent：%s）" % (project_key, enabled_agents(cfg)))
        return 0
    print("未知命令：%s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
