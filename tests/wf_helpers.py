# -*- coding: utf-8 -*-
"""测试公共设施：把 scripts/ 加入 sys.path，提供最小工作流根 / 业务项目目录构造。

所有测试只操作 tmp_path 下的假目录，不触碰真实 execution/ 与并行会话文件。
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


def make_home(root) -> str:
    """最小工作流根结构：config/workflow.yaml + scripts/_config.py + config/projects/。"""
    root = str(root)
    os.makedirs(os.path.join(root, "config", "projects"), exist_ok=True)
    with open(os.path.join(root, "config", "workflow.yaml"), "w", encoding="utf-8") as f:
        f.write("workflow_name: zentao-dev-workflow\nexecution_root: \"${WORKFLOW_HOME}/execution\"\n")
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    with open(os.path.join(root, "scripts", "_config.py"), "w", encoding="utf-8") as f:
        f.write("# 标记文件桩（校验只要求存在）\n")
    return root


def make_project_dir(root, name) -> str:
    """假业务项目目录（无工作流标记），如 Java 后端 / Vue 前端。"""
    p = os.path.join(str(root), name)
    os.makedirs(os.path.join(p, "src", "main"), exist_ok=True)
    with open(os.path.join(p, "README.md"), "w", encoding="utf-8") as f:
        f.write("# %s\n" % name)
    return p
