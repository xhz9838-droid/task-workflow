# -*- coding: utf-8 -*-
"""工作流根目录（WORKFLOW_HOME）统一解析与校验。

背景：Skill 安装在 ~/.claude/skills/（只有 SKILL.md/references/templates），而
config/ 与 execution/ 在工作流仓库里。从任意目录启动时必须先定位工作流根，
再谈配置、执行状态与审计日志。

解析优先级（命中即止）：
  1. 环境变量 WORKFLOW_HOME（显式指定；指向无效目录 → 明确报错，不静默回落）
  2. 用户级工作流配置 ~/.claude/zentao-dev-workflow.json → workflow_home（无效 → 明确报错）
  3. 安装记录 ~/.claude/zentao-dev-workflow.home（install.sh 写入；无效 → 跳过继续）
  4. Skill 开发源 / 脚本所在仓库（通过校验才采用）
  5. 从 start（默认当前目录）向上探测第一个通过校验的目录

校验（validate_home）：
  - 必须同时存在 config/workflow.yaml 与 scripts/_config.py
  - Skill 安装目录（~/.claude/skills/**）永远不是工作流根（不含 config/execution）

CLI：
  python -I scripts/_home.py [--json] [--start DIR]   解析并打印工作流根
  python -I scripts/_home.py --check [--path DIR]     校验目录（默认校验解析结果）
"""
from __future__ import annotations

import json
import os
import re
import sys

# Windows 控制台可能是 GBK，统一强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 校验标记：两者同时存在才认为是工作流根（业务项目目录不可能同时具备）
MARKERS = ("config/workflow.yaml", "scripts/_config.py")
USER_CONFIG_FILE = os.path.join("~", ".claude", "zentao-dev-workflow.json")
INSTALL_RECORD_FILE = os.path.join("~", ".claude", "zentao-dev-workflow.home")

SOURCE_ENV = "环境变量 WORKFLOW_HOME"
SOURCE_USER_CONFIG = "用户级工作流配置"
SOURCE_INSTALL_RECORD = "安装记录"
SOURCE_DEV_SOURCE = "Skill 开发源 / 脚本所在仓库"
SOURCE_PROBE = "自当前目录向上探测"


class HomeError(Exception):
    """无法定位或校验工作流根目录——必须人工处理，不猜测。"""


def _norm(path: str) -> str:
    path = os.path.expanduser(str(path).strip())
    if os.name == "nt":
        # Git Bash 写入的 MSYS 路径（/d/foo → D:/foo）对 Windows Python 不可解析，先转换
        m = re.match(r"^/([A-Za-z])(/.*)?$", path.replace("\\", "/"))
        if m:
            path = "%s:%s" % (m.group(1).upper(), m.group(2) or "/")
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def is_skill_install_dir(path: str) -> bool:
    """路径位于 ~/.claude/skills/**（Skill 安装目录）之下。"""
    parts = _norm(path).split(os.sep)
    for i, seg in enumerate(parts):
        if seg == ".claude" and i + 1 < len(parts) and parts[i + 1] == "skills":
            return True
    return False


def validate_home(path: str) -> list:
    """校验工作流根目录结构。返回问题列表，空列表 = 通过。"""
    if not path or not str(path).strip():
        return ["路径为空"]
    path = _norm(path)
    if not os.path.isdir(path):
        return ["目录不存在：%s" % path]
    problems = []
    if is_skill_install_dir(path):
        problems.append("Skill 安装目录不是工作流仓库（不含 config/execution）")
    for marker in MARKERS:
        if not os.path.isfile(os.path.join(path, marker)):
            problems.append("缺少必要文件：%s" % marker)
    return problems


def _script_home() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_workflow_home(start=None, env=None,
                          user_config_file=None, install_record_file=None,
                          script_home=None):
    """按优先级解析工作流根目录。返回 (绝对路径, 来源)。

    参数（测试可注入；None = 使用真实默认位置）：
      start               向上探测起点（默认当前目录）
      env                 环境变量映射（默认 os.environ）
      user_config_file    用户级配置文件路径
      install_record_file 安装记录文件路径
      script_home         开发源候选（默认 _home.py 所在仓库）

    语义：环境变量 / 用户级配置是显式意图，设置但无效 → 抛 HomeError；
    安装记录 / 开发源 / 向上探测是推导线索，无效 → 跳过继续。
    """
    env = os.environ if env is None else env
    attempts = []

    def _accept(candidate, source, hard):
        """候选有效 → 返回 (path, source)；无效 → 抛错或记入 attempts。"""
        if candidate is None or not str(candidate).strip():
            return None
        path = _norm(candidate)
        problems = validate_home(path)
        if not problems:
            return path, source
        msg = "%s → %s（%s）" % (source, candidate, "；".join(problems))
        if hard:
            raise HomeError(
                "工作流根目录无效：%s\n请修正该来源后重试，不猜测其他路径。" % msg
            )
        attempts.append(msg)
        return None

    # 1) 环境变量 WORKFLOW_HOME
    got = _accept(env.get("WORKFLOW_HOME"), SOURCE_ENV, hard=True)
    if got:
        return got

    # 2) 用户级工作流配置
    uc = os.path.expanduser(user_config_file or USER_CONFIG_FILE)
    if os.path.isfile(uc):
        try:
            with open(uc, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise HomeError("用户级工作流配置无法解析：%s（%s）" % (uc, e))
        if not isinstance(data, dict) or not data.get("workflow_home"):
            raise HomeError("用户级工作流配置 %s 缺少 workflow_home 字段。" % uc)
        got = _accept(data.get("workflow_home"), "%s %s" % (SOURCE_USER_CONFIG, uc), hard=True)
        if got:
            return got

    # 3) 安装记录
    ir = os.path.expanduser(install_record_file or INSTALL_RECORD_FILE)
    if os.path.isfile(ir):
        try:
            with open(ir, encoding="utf-8") as f:
                recorded = (f.read().strip().splitlines() or [""])[0].strip()
        except Exception:
            recorded = ""
        got = _accept(recorded, "%s %s" % (SOURCE_INSTALL_RECORD, ir), hard=False)
        if got:
            return got

    # 4) Skill 开发源 / 脚本所在仓库
    src_home = _script_home() if script_home is None else script_home
    got = _accept(src_home, SOURCE_DEV_SOURCE, hard=False)
    if got:
        return got

    # 5) 自当前目录向上探测
    start_dir = _norm(start) if start else _norm(os.getcwd())
    cur = start_dir
    depth = 0
    while True:
        if not is_skill_install_dir(cur) and not validate_home(cur):
            return cur, "%s（%s）" % (SOURCE_PROBE, start_dir)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
        depth += 1
    attempts.append("%s：自 %s 向上 %d 级均未通过校验" % (SOURCE_PROBE, start_dir, depth))

    raise HomeError(
        "无法定位工作流根目录。已尝试：\n  - %s\n"
        "请任选其一后重试：\n"
        "  1) 设置环境变量 WORKFLOW_HOME 指向工作流仓库\n"
        "  2) 在 %s 配置 {\"workflow_home\": \"<工作流仓库>\"}\n"
        "  3) 运行 <工作流仓库>/scripts/install.sh 写入安装记录\n"
        "  4) 在工作流仓库目录内启动\n"
        % ("\n  - ".join(attempts), os.path.expanduser(USER_CONFIG_FILE))
    )


# --------------------------------------------------------------- CLI
def main(argv):
    args = list(argv[1:])
    fmt_json = "--json" in args
    check_only = "--check" in args
    start = None
    path = None
    if "--start" in args:
        i = args.index("--start")
        start = args[i + 1]
    if "--path" in args:
        i = args.index("--path")
        path = args[i + 1]
    try:
        if check_only:
            target = path or resolve_workflow_home(start)[0]
            problems = validate_home(target)
            if problems:
                print("❌ %s：\n  - %s" % (target, "\n  - ".join(problems)), file=sys.stderr)
                return 3
            print("✅ %s" % target)
            return 0
        home, source = resolve_workflow_home(start)
        if fmt_json:
            print(json.dumps({"home": home, "source": source}, ensure_ascii=False))
        else:
            print(home)
        return 0
    except HomeError as e:
        print("❌ %s" % e, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
