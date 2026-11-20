#!/usr/bin/env bash
# 通过现有 CC Connect（钉钉）向本人发送决策/通知消息。不新建机器人、不读取任何凭据。
# 用法：scripts/notify.sh <task_id> <stage> <blocker_id|-> <message-file>
#   消息头自动带：project_key / ZenTao Task ID / Session ID / Blocker ID / 阶段。
set -uo pipefail

if [[ $# -lt 4 ]]; then
  echo "用法：$0 <task_id> <stage> <blocker_id|-> <message-file>" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 工作流根目录统一解析（见 scripts/_home.py）；解析失败回退脚本所在仓库
ROOT="$(python -I "$SCRIPT_DIR/_home.py" 2>/dev/null)" || ROOT=""
[ -z "$ROOT" ] && ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TASK="$1"; STAGE="$2"; BLOCKER="$3"; BODY_FILE="$4"
PROJECT_KEY="${PROJECT_KEY:-}"

# 任务状态：execution/{project_key}/{task_id}/session.json，回退旧扁平路径
SESSION_JSON="$ROOT/execution/$TASK/session.json"
if [ -n "$PROJECT_KEY" ] && [ -f "$ROOT/execution/$PROJECT_KEY/$TASK/session.json" ]; then
  SESSION_JSON="$ROOT/execution/$PROJECT_KEY/$TASK/session.json"
fi
SID=""; PROJECT=""; SESS=""
if [ -f "$SESSION_JSON" ]; then
  SID=$(python -I -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get('claude_session_id',''))" "$SESSION_JSON" 2>/dev/null) || SID=""
  PROJECT=$(python -I -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get('cc_connect_project',''))" "$SESSION_JSON" 2>/dev/null) || PROJECT=""
  SESS=$(python -I -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get('cc_connect_session',''))" "$SESSION_JSON" 2>/dev/null) || SESS=""
fi

MSG=$(mktemp)
trap 'rm -f "$MSG"' EXIT
{
  echo "【AI研发工作流】"
  echo "Project: ${PROJECT_KEY:--}"
  echo "ZenTao Task: #$TASK"
  echo "Session ID: $SID"
  echo "Blocker ID: $BLOCKER"
  echo "阶段: $STAGE"
  echo "----"
  cat "$BODY_FILE"
} > "$MSG"

ARGS=(send --stdin)
[ -n "$PROJECT" ] && ARGS+=(-p "$PROJECT")
[ -n "$SESS" ] && ARGS+=(-s "$SESS")

# 发送失败不得导致脚本中途退出：先记录 RC，再审计，最后返回 RC
RC=0
cc-connect "${ARGS[@]}" < "$MSG" || RC=$?

AUDIT_ARGS=("$TASK" "ccconnect.send" "{\"project_key\":\"$PROJECT_KEY\",\"stage\":\"$STAGE\",\"blocker\":\"$BLOCKER\",\"rc\":$RC}")
[ -n "$PROJECT_KEY" ] && AUDIT_ARGS+=(--project "$PROJECT_KEY")
python -I "$ROOT/scripts/audit.py" "${AUDIT_ARGS[@]}" >/dev/null 2>&1 || true
exit $RC
