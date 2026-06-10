---
name: socrates
description: Socrates — register an alias for the current Claude session, or check its registration status. Aliased sessions can be found and resumed from the terminal with `socrates list` (short alias `soc list`).
argument-hint: "[alias] | name <alias> | status | help"
disable-model-invocation: true
allowed-tools: Bash(bash:*), Bash(jq:*)
---

# Socrates session alias manager

Current session ID: `${CLAUDE_SESSION_ID}`
Arguments: `$ARGUMENTS`

Registry script: `${CLAUDE_SKILL_DIR}/socreg.sh` (the only write target is `~/.claude/socrates/sessions.json`)

## Rules

Interpret the arguments and perform exactly one of the actions below. Never modify any other file. Respond in the user's language.

Reserved words: `status`, `help` — NEVER register them as aliases.

### 1. No arguments, or `status` — status query

```bash
bash "${CLAUDE_SKILL_DIR}/socreg.sh" "${CLAUDE_SESSION_ID}"
```

Report concisely: the current session ID, its alias (or that none is set), the current project folder, and the total number of registered sessions.

### 2. `help` — usage guidance (do NOT register an alias)

Do not run the script. Explain the usage instead:
- `/socrates <alias>` — register an alias for the current session
- `/socrates status` — show current session ID and alias
- Terminal: `socrates list` (short `soc`) — pick a session → `--resume <UUID>` is copied to the clipboard; `socrates map` / `report` — settings overview

### 3. Anything else — register an alias

- If the arguments look like `name <alias>`, use only the text after `name`.
- Otherwise use the full argument text as the alias.
- Replace spaces in the alias with hyphens (`-`).

```bash
bash "${CLAUDE_SKILL_DIR}/socreg.sh" "${CLAUDE_SESSION_ID}" "<alias>" "$PWD"
```

If stderr warns that the alias is already used by another session, tell the user — the registration still succeeded (overwrite policy).

On success, report:
- the registered alias and session ID
- that the session can be found with `socrates list` (short `soc list`) in the terminal, where Enter copies `--resume <UUID>` to the clipboard
