---
name: name
description: Socrates — register a unique alias for the current Claude session so it can be found and resumed from the terminal with `socrates list`.
argument-hint: "<alias>"
disable-model-invocation: true
allowed-tools: Bash(bash:*), Bash(jq:*)
---

# Socrates — name this session

Current session ID: `${CLAUDE_SESSION_ID}`
Arguments: `$ARGUMENTS`

Registry script: `${CLAUDE_SKILL_DIR}/socreg.sh` (the only write target is `~/.claude/socrates/sessions.json`)

## Rules

Respond in the user's language. Never modify any file other than via socreg.sh.

### Reserved words — NEVER register these as aliases

If the argument is one of `list`, `ls`, `map`, `report`, `doctor`, `version`, `update`, `unname`, `help`, `도움말`, `soc`, `socrates`: the user almost certainly meant a **terminal command**, not an alias. Do NOT run the registry script. Explain instead:

- Those are terminal commands: run `socrates list` / `map` / `report` / `doctor` / `update` / `unname` in a shell, outside Claude.
- To name this session: `/socrates:name <alias>` — e.g. `/socrates:name proposal-hwpx`
- To check this session: `/socrates:status`

Exception: if the argument is `status`, run the status query instead of registering:

```bash
bash "${CLAUDE_SKILL_DIR}/socreg.sh" "${CLAUDE_SESSION_ID}"
```

### Registering an alias

- If the arguments look like `name <alias>`, use only the text after `name`.
- Replace spaces in the alias with hyphens (`-`).

```bash
bash "${CLAUDE_SKILL_DIR}/socreg.sh" "${CLAUDE_SESSION_ID}" "<alias>" "$PWD"
```

Interpret the result and report it faithfully:

- **Exit 1, "already used by another session"** — registration was REJECTED (aliases are unique across sessions). Tell the user which session/project holds the name, and suggest a different alias (e.g. main-sub naming such as `proposal-hwpx`) or freeing it with `socrates unname` in the terminal.
- **"Updated alias: \"old\" → \"new\""** — tell the user the previous alias was replaced, naming both.
- **"Alias unchanged"** — say it was already set to that name.
- **"Registered:"** — report the new alias and session ID, and that `socrates list` in the terminal will show it (Enter copies `--resume <UUID>` to the clipboard).
