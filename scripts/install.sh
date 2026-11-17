#!/usr/bin/env bash
# zentao-dev-workflow 个人级安装/卸载
# 用法：
#   scripts/install.sh              安装/更新 Skill + Agents 到 ~/.claude/
#   scripts/install.sh --uninstall  卸载（只删本工作流安装的，不动用户已有 Skill/Agent）
#   scripts/install.sh --link       用软链（Windows: junction）代替复制，改源码即时生效
#
# 原则：
#   - 不破坏用户已有的个人 Skill / Agent（只写本工作流的文件名）
#   - 已存在同名用户文件 → 备份为 .bak.<时间戳> 后覆盖，并提示
#   - 开发源始终在 {WORKFLOW_HOME}/.claude/skills/zentao-dev-workflow/

set -euo pipefail

WORKFLOW_HOME="$(cd "$(dirname "$0")/.." && pwd)"
USER_CLAUDE="${USERPROFILE:-$HOME}/.claude"
# 布局自适应：公司仓库用 skill/ 子目录，个人开发仓库用 .claude/skills/ 布局
if [[ -d "$WORKFLOW_HOME/skill" ]]; then
  SKILL_SRC="$WORKFLOW_HOME/skill"
  AGENTS_SRC="$WORKFLOW_HOME/agents"
elif [[ -d "$WORKFLOW_HOME/.claude/skills/zentao-dev-workflow" ]]; then
  SKILL_SRC="$WORKFLOW_HOME/.claude/skills/zentao-dev-workflow"
  AGENTS_SRC="$WORKFLOW_HOME/.claude/agents"
else
  echo "✗ 未找到 skill 源目录（尝试 $WORKFLOW_HOME/skill 与 $WORKFLOW_HOME/.claude/skills/zentao-dev-workflow）" >&2
  exit 1
fi
SKILL_NAME="zentao-dev-workflow"
TS="$(date +%Y%m%d%H%M%S)"

MODE="install"
LINK=0
for a in "$@"; do
  case "$a" in
    --uninstall) MODE="uninstall" ;;
    --link) LINK=1 ;;
  esac
done

# dw- 前缀避免覆盖用户已有的同名个人 Agent（安装/卸载不破坏用户文件）
AGENT_NAMES=(dw-architect dw-database dw-java-backend dw-web-frontend dw-mobile-app dw-qa-engineer dw-integration-reviewer)

backup_if_exists() {
  local f="$1"
  if [[ -e "$f" && ! -L "$f" ]]; then
    local bak="$f.bak.$TS"
    cp -r "$f" "$bak"
    echo "  ⚠ 已备份原有 → $(basename "$bak")"
  fi
}

do_install() {
  echo "== 安装 zentao-dev-workflow 到 $USER_CLAUDE =="
  mkdir -p "$USER_CLAUDE/skills" "$USER_CLAUDE/agents"

  # Skill（本工作流专属命名，直接替换旧版本；用户其他 Skill 不受影响）
  local dst="$USER_CLAUDE/skills/$SKILL_NAME"
  rm -rf "$dst"
  if [[ $LINK -eq 1 ]]; then
    if command -v cmd.exe >/dev/null 2>&1 && [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* ]]; then
      cmd.exe /c "mklink /J \"$(cygpath -w "$dst" 2>/dev/null || echo "$dst")\" \"$(cygpath -w "$SKILL_SRC" 2>/dev/null || echo "$SKILL_SRC")\"" >/dev/null
    else
      ln -s "$SKILL_SRC" "$dst"
    fi
    echo "  ✓ Skill 已软链 → $dst"
  else
    cp -r "$SKILL_SRC" "$dst"
    echo "  ✓ Skill 已安装 → $dst"
  fi

  # 兼容别名（§五 命名）
  local alias_dst="$USER_CLAUDE/skills/dev-workflow"
  if [[ ! -e "$alias_dst" ]]; then
    if command -v cmd.exe >/dev/null 2>&1 && [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* ]]; then
      cmd.exe /c "mklink /J \"$(cygpath -w "$alias_dst" 2>/dev/null || echo "$alias_dst")\" \"$(cygpath -w "$dst" 2>/dev/null || echo "$dst")\"" >/dev/null 2>&1 || true
    else
      ln -s "$dst" "$alias_dst" 2>/dev/null || true
    fi
    echo "  ✓ 兼容别名 dev-workflow 已创建"
  fi

  # Agents（dw- 前缀专属命名，不与用户已有 Agent 同名，故不备份/不覆盖用户文件）
  for n in "${AGENT_NAMES[@]}"; do
    local af="$USER_CLAUDE/agents/$n.md"
    if [[ -e "$af" && ! -L "$af" ]]; then
      # 同名文件仅可能是本工作流上一次安装的副本 → 直接替换（不动用户文件）
      rm -rf "$af"
    fi
    cp "$AGENTS_SRC/$n.md" "$af"
    echo "  ✓ Agent $n.md"
  done

  echo ""
  echo "安装完成。在任意项目根目录启动 Claude Code 后可调用："
  echo "  /$SKILL_NAME <project_key> <task_id>"
  echo ""
  echo "配置：把 config/*.example.yaml 复制为实际文件并填写；凭据放 .env。"
}

# 工作流根安装记录：Skill 从任意目录启动时按此定位 config/ 与 execution/（见 scripts/_home.py）
write_install_record() {
  local record="$USER_CLAUDE/zentao-dev-workflow.home"
  # pwd -W：Git Bash 下写 Windows 原生路径（/d/... 形式 Windows Python 无法解析）
  local native
  native="$(cd "$WORKFLOW_HOME" && pwd -W 2>/dev/null)" || native="$WORKFLOW_HOME"
  printf '%s\n' "$native" > "$record"
  echo "  ✓ 工作流根安装记录 → $record"
}

do_uninstall() {
  echo "== 卸载 $SKILL_NAME =="
  for d in "$USER_CLAUDE/skills/$SKILL_NAME" "$USER_CLAUDE/skills/dev-workflow"; do
    if [[ -e "$d" ]]; then rm -rf "$d"; echo "  ✓ 移除 $d"; fi
  done
  for n in "${AGENT_NAMES[@]}"; do
    local af="$USER_CLAUDE/agents/$n.md"
    if [[ -e "$af" ]]; then rm -f "$af"; echo "  ✓ 移除 $af"; fi
  done
  local record="$USER_CLAUDE/zentao-dev-workflow.home"
  if [[ -e "$record" ]]; then rm -f "$record"; echo "  ✓ 移除 $record"; fi
  echo "卸载完成（用户其他 Skill/Agent 未动）。"
}

if [[ "$MODE" == "uninstall" ]]; then do_uninstall; else do_install; write_install_record; fi
