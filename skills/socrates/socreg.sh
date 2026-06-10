#!/bin/bash
# Socrates alias registry — register an alias for a session UUID, or query status.
# Usage: socreg.sh <session-id> [alias] [cwd]
#   without alias → status query / with alias → register (overwrite allowed)
# The ONLY write target is ~/.claude/socrates/sessions.json.
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
    "alias:    \(.[$id].alias // "(none)")",
    "named_at: \(.[$id].named_at // "-")",
    "registered_total: \(length)"' "$REG"
  exit 0
fi

DUP=$(jq -r --arg a "$ALIAS" --arg id "$SID" \
  'to_entries[] | select(.value.alias == $a and .key != $id) | .key' "$REG")
[ -n "$DUP" ] && echo "Warning: alias \"$ALIAS\" is already used by another session: $DUP" >&2

TMP=$(mktemp)
jq --arg id "$SID" --arg alias "$ALIAS" --arg cwd "$CWD" \
   --arg t "$(date +%Y-%m-%dT%H:%M:%S%z)" \
   '.[$id] = {alias: $alias, cwd: $cwd, named_at: $t}' "$REG" > "$TMP"
mv "$TMP" "$REG"

echo "Registered: $SID → \"$ALIAS\""
echo "Find it with 'socrates list' (short: soc list), or resume with '--resume $SID'."
