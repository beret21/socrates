# Socrates — "Know Your Self"

> A session & settings manager for Claude Code
> γνῶθι σεαυτόν — Know thyself. Know your Claude environment.

Written: 2026-06-10

---

## 1. Problem

Running many Claude Code CLI sessions at once creates two problems.

| # | Problem | Status quo |
|---|---------|-----------|
| 1 | **Hard to get back to a session** — after a reboot (OS update, etc.) it is hard to find the session you were working in | `claude --resume <UUID>` works, but there is no way to manage UUIDs |
| 2 | **Hard to see what is configured** — settings scattered across `~/.claude/` and per-project `.claude/`, plus the growing fleet of subagents/skills from harness engineering | You have to open every folder by hand |

## 2. Approach (agreed)

| Area | Decision |
|------|----------|
| Inside Claude | `/socrates` slash command assigns an alias to the current session |
| Terminal | standalone `socrates` command (short alias `soc`) + optional `claude soc ...` zsh wrapper |
| Picking a session | fzf TUI; selection **copies `--resume <UUID>` to the clipboard** (no auto-launch — the user composes flags like `--dangerously-skip-permissions` manually) |
| Status views | terminal summary `socrates map` + static HTML dashboard `socrates report` |
| Stack | picker: shell + fzf + jq / analysis & HTML: Python stdlib only |

## 3. Ground truth (official docs + local verification, 2026-06-10)

- **Session storage**: `~/.claude/projects/<path with '/' encoded as '-'>/<sessionUUID>.jsonl`
  - each line carries `sessionId`, `cwd`, `timestamp`, `gitBranch`, `slug` (auto-generated name), `version`
- **Getting the session ID**: `${CLAUDE_SESSION_ID}` substitution inside SKILL.md is officially supported — [docs/skills](https://code.claude.com/docs/en/skills)
- **Skill location**: `~/.claude/skills/<name>/SKILL.md` (user-global) — [docs/skills](https://code.claude.com/docs/en/skills)
- **Resume**: `claude --resume "<id>"` / `claude -r` — [docs/cli-reference](https://code.claude.com/docs/en/cli-reference)
- **Project metadata**: `projects` key in `~/.claude.json` — `lastSessionId`, cost, model usage
- **No name collisions**: no user commands in `~/.claude/skills/` or `~/.claude/commands/`
- **Caveat**: custom flags like `claude --soc` are not supported → route `claude soc ...` through a zsh wrapper function

## 4. Architecture

```
┌─ Inside a Claude session ──────────┐    ┌─ Terminal ────────────────────────┐
│  /socrates <alias>                 │    │  socrates list   (fzf picker)     │
│  └─ records ${CLAUDE_SESSION_ID}   │    │  socrates name   (set alias)      │
│     + cwd                          │    │  socrates map    (status, TTY)    │
│                                    │    │  socrates report (HTML dashboard) │
└──────────────┬─────────────────────┘    └──────┬────────────────────────────┘
               │ write                           │ read/write
               ▼                                 ▼
        ~/.claude/socrates/sessions.json  ← alias registry (the ONLY write target)
               ▲                                 │ read-only
               │                                 ▼
   ~/.claude/projects/*/*.jsonl   ~/.claude/settings.json    ~/.claude.json
   (session transcripts)          (+ hierarchy of .claude/)  (project metadata)
```

### Layout

```
Socrates/
├── plan/PLAN.md, PLAN.html    # this design document
├── bin/socrates               # CLI entry point (bin/soc = short-alias symlink)
├── lib/soc-sessions.sh        # session scanner + fzf picker
├── lib/soc_report.py          # settings analysis + terminal summary + HTML
├── skills/socrates/SKILL.md   # /socrates slash command
├── install.sh                 # manual install (symlinks + wrapper guidance)
└── README.md / README.ko.md
```

### Data: `~/.claude/socrates/sessions.json`

```json
{
  "123e4567-e89b-12d3-a456-426614174000": {
    "alias": "socrates-bootstrap",
    "cwd": "~/Projects/Socrates",
    "named_at": "2026-06-10T08:30:00+09:00"
  }
}
```

## 5. Command spec

### `/socrates` (inside a Claude session)

| Usage | Behavior |
|-------|----------|
| `/socrates <alias>` or `/socrates name <alias>` | record an alias for the current session UUID |
| `/socrates` or `/socrates status` | show current session ID, alias, project, registry count |
| `/socrates help` | usage guidance (reserved word — never registered as an alias) |

- `disable-model-invocation: true` — user-invoked only
- minimal permissions: `Bash(bash:*)`, `Bash(jq:*)`

### `socrates` (terminal; short alias `soc`)

| Command | Behavior |
|---------|----------|
| `socrates` / `socrates list` | fzf list: aliased sessions (★, on top) + ~50 recent. **Enter → copies `--resume <UUID>`**, Ctrl-Y → UUID only |
| `socrates name [alias]` | pick a session, set/update its alias |
| `socrates map` | settings hierarchy (global → parents → project), hooks, plugins, MCP, skills/agents as an ANSI tree |
| `socrates report` | generate `~/.claude/socrates/report.html` and open it |
| `socrates version` | print the plugin version |

fzf preview pane: full path, gitBranch, recent user messages.

### HTML report sections

1. Projects × sessions table (aliases highlighted, copy buttons for `--resume UUID`)
2. Settings hierarchy tree (global → parent folders → project)
3. Harness inventory: agents / skills / plugins / MCP servers
4. Cost & model-usage summary (from `~/.claude.json`)

## 6. Safety principles

- Session jsonl files under `~/.claude/projects/` are **read-only** — writes go only under `~/.claude/socrates/`
- Never auto-edit `~/.zshrc` — print the wrapper snippet only
- Parse only the head/tail of large jsonl files
- macOS-first (pbcopy, open). Dependencies: fzf, jq

## 7. Verification plan

| Step | How to verify |
|------|---------------|
| /socrates skill | run `/socrates name test`, check `sessions.json` |
| socrates list | pick → `pbpaste` == `--resume <uuid>` → actually resume with `claude --resume` |
| socrates map/report | output matches real settings (project folders, active plugins) |
| wrapper | `claude soc list` == `soc list`, `command claude --version` still works |

---

## Decision log

### 2026-06-10 (post-implementation)

1. **One name**: the canonical name is `socrates`. Slash command `/socrates` (autocomplete removes the typing cost; a proper noun minimizes collision risk with future built-ins), terminal `socrates` + short alias `soc`. Skill folder `skills/soc` → `skills/socrates`.
2. **Distribution**: plugin structure added (`.claude-plugin/plugin.json` + `marketplace.json` + `hooks/hooks.json`). The repo is its own marketplace — `/plugin marketplace add beret21/socrates` → `/plugin install socrates@beret21`. A SessionStart hook links the CLI into `~/.local/bin`, so no split install. Manual `install.sh` remains as a secondary path.
3. **White-background HTML**: all HTML artifacts use a light theme.
4. **Security cleanup**: published history rewritten to a single clean commit; examples in docs use placeholder UUIDs/paths; `History/` (communication snapshots, Korean) and auto-generated `CLAUDE.md` files are local-only via `.gitignore`.
5. **English everywhere**: commit messages, docs, code comments, and CLI output are English; `README.ko.md` is the Korean secondary README.

### 2026-06-11 (v0.13, from real-world testing on a second machine)

6. **Aliases are unique across sessions** — rejected with an error, no `--force` escape hatch. Rationale: the tool exists to distinguish concurrent sessions (often several in the SAME project folder, e.g. draft/hwpx/images), named with a main-sub convention; duplicate aliases would defeat that purpose, and corrections are already covered by overwrite + `unname`.
7. **Terminal-first update**: `socrates update` performs the plugin update AND relinks the CLI immediately — no Claude session needed. Releases are complete copies; version skipping is safe by design (no migrations, old registry formats must stay readable).
8. **Skill split**: `/socrates:socrates` → `/socrates:name` + `/socrates:status` (removes the doubled name, and `/socrates:` autocompletion now lists sub-features). CLI subcommand words (list, map, report, …) are reserved in the skill and produce guidance instead of being registered as aliases.
9. **`claude --resume` is project-scoped** (confirmed empirically): the picker now prints `cd "<dir>" && claude --resume <uuid>` and Ctrl-O copies that whole command.

### 2026-06-11 (v0.15, after surveying Claude's native features)

10. **v0.20 — Config X-ray (structural)**: the dashboard became a tabbed single-file HTML (Overview/Projects/Sessions/Config X-ray/Harness). Static HTML over a local server: a settings snapshot has no use for live serving, and a file means no process/port management and archivable snapshots. Two-layer config model (global + project) for settings, with one exception verified in the official docs AND empirically in this session: **CLAUDE.md walks UP the directory tree** (root→cwd, all concatenated — https://code.claude.com/docs/en/memory#how-claude-md-files-load), so the X-ray's headline feature is the per-project CLAUDE.md chain with sizes and ancestor warnings. Version written as 0.20 (not 0.2) so version comparison stays monotonic.

11. **Integrate, don't compete**: a docs/CHANGELOG survey showed Claude Code now has native session naming (`claude -n`, `/rename`, picker `Ctrl+R`) and `--resume <name>`. Socrates therefore reads native names (stored as `customTitle` in the transcript — verified empirically) and shows them in the picker (priority: alias → native → slug → first message), and repositions around what native lacks: **full-text transcript search** (`socrates find`, native searches metadata only), all-projects-by-default scope, copy-not-launch, after-the-fact naming, and the settings/harness map/report/doctor (no native equivalent). Re-run this overlap survey quarterly.
