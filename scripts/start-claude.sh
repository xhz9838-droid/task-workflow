#!/usr/bin/env bash
# 在工作流根启动 Claude Code，并把业务仓库以 --add-dir 注册（读取本机 .env 的路径）。
# 路径全部来自环境变量/配置，不写死任何仓库绝对路径。
set -euo pipefail

# 工作流根：优先环境变量，回退脚本自身推导（scripts 的父目录）
WORKFLOW_ROOT="${WORKFLOW_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$WORKFLOW_ROOT"

# 从本机 .env 读取项目仓库路径（VAR=VALUE），组装 REPOS
# 仅收集匹配 *_ROOT / *_SANITATION / *_UPMS / *_WEB / *_APP 的路径（业务仓库）
REPOS=()
if [[ -f "$WORKFLOW_ROOT/.env" ]]; then
  while IFS='=' read -r key val; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    case "$key" in
      WORKFLOW_HOME|JENKINS_*|ZENTAO_*|CC_*|USER_*|DEMO_*) continue ;;
      *_ROOT|*_SANITATION|*_UPMS|*_WEB|*_APP)
        [[ -z "$val" ]] && continue
        REPOS+=("$val")
        ;;
    esac
  done < "$WORKFLOW_ROOT/.env"
fi

export CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1

for repo in "${REPOS[@]}"; do
  if [[ ! -d "$repo/.git" && ! -f "$repo/.git" ]]; then
    echo "错误：Git 仓库不存在或不是有效 Worktree：$repo" >&2
    exit 1
  fi
done

echo "研发控制中心：$WORKFLOW_ROOT"
echo "已注册业务仓库：${#REPOS[@]}"

if [[ ${#REPOS[@]} -gt 0 ]]; then
  claude --add-dir "${REPOS[@]}" "$@"
else
  claude "$@"
fi