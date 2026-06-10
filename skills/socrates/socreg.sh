#!/bin/bash
# Socrates alias 레지스트리 — 세션 UUID에 별명을 등록하거나 상태를 조회한다.
# 사용법: socreg.sh <session-id> [alias] [cwd]
#   alias 없음 → 상태 조회 / alias 있음 → 등록(덮어쓰기)
# 쓰기 대상은 ~/.claude/socrates/sessions.json 뿐이다.
set -euo pipefail

SID="${1:?usage: socreg.sh <session-id> [alias] [cwd]}"
ALIAS="${2:-}"
CWD="${3:-$PWD}"
DIR="$HOME/.claude/socrates"
REG="$DIR/sessions.json"

mkdir -p "$DIR"
[ -f "$REG" ] || printf '{}\n' > "$REG"

if [ -z "$ALIAS" ]; then
  jq -r --arg id "$SID" '
    "session:  \($id)",
    "alias:    \(.[$id].alias // "(없음)")",
    "named_at: \(.[$id].named_at // "-")",
    "registered_total: \(length)"' "$REG"
  exit 0
fi

DUP=$(jq -r --arg a "$ALIAS" --arg id "$SID" \
  'to_entries[] | select(.value.alias == $a and .key != $id) | .key' "$REG")
[ -n "$DUP" ] && echo "주의: 별명 \"$ALIAS\" 은(는) 이미 다른 세션에 사용 중: $DUP" >&2

TMP=$(mktemp)
jq --arg id "$SID" --arg alias "$ALIAS" --arg cwd "$CWD" \
   --arg t "$(date +%Y-%m-%dT%H:%M:%S%z)" \
   '.[$id] = {alias: $alias, cwd: $cwd, named_at: $t}' "$REG" > "$TMP"
mv "$TMP" "$REG"

echo "등록 완료: $SID → \"$ALIAS\""
echo "터미널에서 'socrates list' (단축: soc list) 로 찾거나, '--resume $SID' 로 재개할 수 있습니다."
