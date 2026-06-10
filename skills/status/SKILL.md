---
name: status
description: Socrates — show the current Claude session's ID, alias, and registry status.
disable-model-invocation: true
allowed-tools: Bash(jq:*), Bash(bash:*)
---

# Socrates — session status

Current session ID: `${CLAUDE_SESSION_ID}`

Run this read-only query (handle a missing registry gracefully):

```bash
REG="$HOME/.claude/socrates/sessions.json"
if [ -f "$REG" ]; then
  jq -r --arg id "${CLAUDE_SESSION_ID}" '
    "session:  \($id)",
    "alias:    \(.[$id].alias // "(none)")",
    "named_at: \(.[$id].named_at // "-")",
    "registered_total: \(length)"' "$REG"
else
  echo "registry not created yet (no aliases registered on this machine)"
fi
```

Report in the user's language: the session ID, its alias (or that none is set — suggest `/socrates:name <alias>`), the current project folder (`$PWD`), and the total number of registered sessions. Mention that `socrates list` in the terminal finds sessions and copies `--resume <UUID>` to the clipboard.
