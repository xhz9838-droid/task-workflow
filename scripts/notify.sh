#!/usr/bin/env bash
# 通过现有 CC Connect（钉钉）向本人发送决策/通知消息。不新建机器人、不读取任何凭据。
# 用法：scripts/notify.sh <task_id> <stage> <blocker_id|-> <message-file>
#   消息头自动带：ZenTao Task ID / Session ID / Blocker ID / 阶段。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASK="$1"; STAGE="$2"; BLOCKER="$3"; BODY_FILE="$4"
PROJECT_KEY="${PROJECT_KEY:-}"
# 任务状态：execution/{project_key}/{task_id}/session.json，回退旧扁平路径
if [ -n "$PROJECT_KEY" ] && [ -f "$ROOT/execution/$PROJECT_KEY/$TASK/session.json" ]; then
  SESSION_JSON="$ROOT/execution/$PROJECT_KEY/$TASK/session.json"
else
  SESSION_JSON="$ROOT/execution/$TASK/session.json"
fi
SID=$(python -I -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get('claude_session_id',''))" "$SESSION_JSON")
PROJECT=$(python -I -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get('cc_connect_project',''))" "$SESSION_JSON")
SESS=$(python -I -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get('cc_connect_session',''))" "$SESSION_JSON")

MSG=$(mktemp)
{
  echo "【AI研发工作流】"
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
cc-connect "${ARGS[@]}" < "$MSG"
RC=$?
AUDIT_ARGS=("$TASK" "ccconnect.send" "{\"stage\":\"$STAGE\",\"blocker\":\"$BLOCKER\",\"rc\":$RC}")
[ -n "$PROJECT_KEY" ] && AUDIT_ARGS+=(--project "$PROJECT_KEY")
python -I "$ROOT/scripts/audit.py" "${AUDIT_ARGS[@]}" >/dev/null
rm -f "$MSG"
exit $RC
