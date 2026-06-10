# Socrates — "Know Your Self"

> γνῶθι σεαυτόν — A session & settings manager for Claude Code

**English** | [한국어](README.ko.md)

When you run many Claude Code CLI sessions, two things get hard: (1) finding your way back to the session you were working in after a reboot, and (2) understanding what is actually configured across `~/.claude/` and per-project `.claude/` directories (hooks, plugins, MCP servers, skills, agents). Socrates solves both.

> **Platform**: macOS only for now (uses `pbcopy`, `open`, BSD `stat`). Linux/WSL and native Windows support are on the roadmap.

## Install

### Option A — Plugin (recommended)

Inside Claude Code:

```
/plugin marketplace add beret21/socrates
/plugin install socrates@beret21
```

This registers the `/socrates` skill, and a SessionStart hook links the `socrates` / `soc` CLI into `~/.local/bin` — so from your next session onward the CLI also works in a plain terminal.

### Option B — Manual

```bash
git clone https://github.com/beret21/socrates.git
cd socrates && ./install.sh        # dependencies: brew install fzf jq
```

Neither method modifies your `~/.zshrc`.

## Usage

### Inside a Claude session — name your session

```
/socrates my-task-name    # register an alias for the current session
/socrates status          # show current session ID and alias
```

### In the terminal — `socrates` (short alias: `soc`)

| Command | What it does |
|---------|--------------|
| `socrates` / `socrates list` | fzf session picker. **Enter → copies `--resume <UUID>` to clipboard**, Ctrl-Y → copies the UUID only |
| `socrates name [alias]` | pick a session and set/update its alias |
| `socrates map` | print the settings hierarchy, hooks, plugins, MCP servers, and skills/agents inventory |
| `socrates report` | generate an HTML dashboard (light theme) and open it in the browser |
| `socrates doctor` | check the environment: dependencies, install links, registry integrity, orphaned aliases, version |
| `socrates version` | print the installed version and check GitHub for updates |

The copied value composes freely with other flags:

```bash
claude --resume <UUID> --dangerously-skip-permissions
```

## Layout

```
.claude-plugin/        # plugin.json + marketplace.json (this repo is its own marketplace)
bin/socrates           # CLI entry point (bin/soc is a short-alias symlink)
hooks/hooks.json       # SessionStart: links the CLI into ~/.local/bin
lib/soc-sessions.sh    # session scanner + fzf picker
lib/soc_report.py      # settings analyzer + HTML dashboard (Python stdlib only)
skills/socrates/       # /socrates slash command + alias registry script
plan/                  # design document
```

Data lives in `~/.claude/socrates/`: `sessions.json` (alias registry) and `report.html`.

## Safety principles

- Session transcripts under `~/.claude/projects/` are treated as **read-only** — never modified
- Writes go only to `~/.claude/socrates/`
- No automatic edits to `~/.zshrc`

## Updates

Updates are manual by default. Commands check GitHub for a newer version at most once a day and append a one-line notice when one exists; `socrates version` always performs a live check. Update with `/plugin update socrates@beret21` (plugin) or `git pull` (manual install). Run `socrates doctor` before/after updating to verify the environment.

## Versioning

`#.##` — humble by design; 1.0 is far away. The first decimal bumps on structural changes, the second on spec refinements and added checks.

## Environment variables

- `SOC_EXCLUDE` — `grep -E` pattern of working directories to hide from the session list (default: claude-mem observer sessions)

## License

[MIT](LICENSE)
