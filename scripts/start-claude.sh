#!/usr/bin/env bash
set -euo pipefail

WORKFLOW_ROOT="/d/WorkSpace/task-workflow"

REPOS=(
  "/d/WorkSpace/jeebootx/jeebootx-sanitation"
  "/d/WorkSpace/jeebootx/jeebootx"
  "/d/WorkSpace/jeebootx/jeebootx-ui"
  "/d/WorkSpace/jeebootx/jeebootx-app"
)

cd "$WORKFLOW_ROOT"

export CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1

for repo in "${REPOS[@]}"; do
  if [[ ! -d "$repo/.git" && ! -f "$repo/.git" ]]; then
    echo "错误：Git 仓库不存在或不是有效 Worktree：$repo"
    exit 1
  fi
done

echo "研发控制中心：$WORKFLOW_ROOT"
echo "已注册业务仓库：${#REPOS[@]}"

claude --add-dir "${REPOS[@]}" "$@"