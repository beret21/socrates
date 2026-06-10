#!/bin/bash
# Socrates alias registry — the ONLY writer of ~/.claude/socrates/sessions.json.
# Aliases are UNIQUE across sessions: registering a name already used by
# another session fails (free it first with 'socrates unname', or pick another).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  socreg.sh <session-id>                 show the session's alias status
  socreg.sh <session-id> <alias> [cwd]   register an alias (unique across sessions)
  socreg.sh <session-id> --delete        remove the session's alias
EOF
}

case "${1:-}" in
  ""|-h|--help) usage; exit 0;;
esac

SID="$1"
DIR="$HOME/.claude/socrates"
REG="$DIR/sessions.json"

mkdir -p "$DIR"
[ -f "$REG" ] || printf '{}\n' > "$REG"

# ── delete mode ──────────────────────────────────────────────
if [ "${2:-}" = "--delete" ]; then
  PREV=$(jq -r --arg id "$SID" '.[$id].alias // ""' "$REG")
  if [ -z "$PREV" ]; then
    echo "No alias registered for session $SID — nothing to remove."
    exit 0
  fi
  TMP=$(mktemp)
  jq --arg id "$SID" 'del(.[$id])' "$REG" > "$TMP"
  mv "$TMP" "$REG"
  echo "Removed alias \"$PREV\" from session $SID (the session itself is untouched)."
  exit 0
fi

ALIAS="${2:-}"
CWD="${3:-$PWD}"

# ── status mode ──────────────────────────────────────────────
if [ -z "$ALIAS" ]; then
  jq -r --arg id "$SID" '
    "session:  \($id)",
    "alias:    \(.[$id].alias // "(none)")",
    "named_at: \(.[$id].named_at // "-")",
    "registered_total: \(length)"' "$REG"
  exit 0
fi

# ── register mode ────────────────────────────────────────────
# Uniqueness: an alias held by ANOTHER session is an error, not a warning.
DUP=$(jq -r --arg a "$ALIAS" --arg id "$SID" \
  'to_entries[] | select(.value.alias == $a and .key != $id) | .key' "$REG")
if [ -n "$DUP" ]; then
  DUP_CWD=$(jq -r --arg id "$DUP" '.[$id].cwd // "?"' "$REG")
  echo "Error: alias \"$ALIAS\" is already used by another session" >&2
  echo "       session $DUP in ${DUP_CWD/#$HOME/~}" >&2
  echo "Pick a different name, or free it first with 'socrates unname'." >&2
  exit 1
fi

PREV=$(jq -r --arg id "$SID" '.[$id].alias // ""' "$REG")

TMP=$(mktemp)
jq --arg id "$SID" --arg alias "$ALIAS" --arg cwd "$CWD" \
   --arg t "$(date +%Y-%m-%dT%H:%M:%S%z)" \
   '.[$id] = {alias: $alias, cwd: $cwd, named_at: $t}' "$REG" > "$TMP"
mv "$TMP" "$REG"

if [ -z "$PREV" ]; then
  echo "Registered: $SID → \"$ALIAS\""
elif [ "$PREV" = "$ALIAS" ]; then
  echo "Alias unchanged: \"$ALIAS\" (timestamp refreshed)"
else
  echo "Updated alias: \"$PREV\" → \"$ALIAS\" (the previous alias was overwritten)"
fi
echo "Find it with 'socrates list' (short: soc list), or resume with '--resume $SID'."
