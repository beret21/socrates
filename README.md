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
/socrates:name my-task-name    # register a unique alias for the current session
/socrates:status               # show current session ID and alias
```

Aliases are **unique across sessions** — the tool exists to tell concurrent sessions apart (e.g. `proposal-draft`, `proposal-hwpx`, `proposal-images` in the same project folder), so registering a name another session already holds is rejected. Typed the wrong name? Just register again (overwrites, telling you what it replaced) or free a name with `socrates unname`.

(With the manual install the commands are `/socrates-name` and `/socrates-status`.)

### In the terminal — `socrates` (short alias: `soc`)

| Command | What it does |
|---------|--------------|
| `socrates` / `socrates list` | fzf session picker. **Enter → copies `--resume <UUID>`**, Ctrl-O → copies the full `cd … && claude --resume …` command, Ctrl-Y → UUID only, Ctrl-N → name the highlighted session |
| `socrates find <text>` | **full-text search across every session transcript** on this machine — something the native picker cannot do. Matches open in the same picker, with matching snippets highlighted in the preview |
| `socrates name [alias]` | pick a session and set/update its alias |
| `socrates unname` | pick an alias and remove it (the session itself is untouched) |
| `socrates map` | print the settings hierarchy, hooks, plugins, MCP servers, and skills/agents inventory |
| `socrates report` | generate an HTML dashboard (light theme) and open it in the browser |
| `socrates update` | update everything from the terminal: plugin (skill + CLI) and relink — no Claude session needed. Manual installs do `git pull` |
| `socrates doctor [--fix]` | check the environment: dependencies, PATH, install links, registry integrity, orphaned aliases, version. `--fix` repairs missing/broken CLI links |
| `socrates version` | print the installed version and check GitHub for updates |

**Note:** `claude --resume` finds sessions only from their own project folder — run it after `cd`-ing there (the picker prints the exact command, and Ctrl-O copies it whole):

```bash
cd "/path/to/that/project" && claude --resume <UUID> --dangerously-skip-permissions
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

## Relationship to Claude Code's native features

Claude Code itself ships session tools — Socrates integrates with them instead of competing:

- **Native session names** (`claude -n`, `/rename`) are read and displayed by the picker. Name priority: ★ Socrates alias → native name → auto slug → first message.
- **Resume-and-enter** is what the native `claude --resume` picker already does well (search by name/first prompt, `Ctrl+A` for all projects). Use it when you just want to jump in.
- **Socrates adds what native lacks**: full-text transcript search (`find`), all-projects scope by default, copy-instead-of-launch (compose your own flags), naming sessions after the fact without opening them, the settings/harness map & HTML report, and `doctor`.

## Troubleshooting

**`Plugin "socrates" not found in marketplace "beret21"`** — the marketplace is not registered on this machine yet. Installation is always two steps: `claude plugin marketplace add beret21/socrates` first, then `claude plugin install socrates@beret21`.

**`Plugin "socrates/beret21" not found`** — separator mix-up. `/` is only for the GitHub coordinate in `marketplace add beret21/socrates` (owner/repo); every install/update/uninstall uses `@`: `socrates@beret21` (plugin@marketplace). Rule of thumb: `/` points outside (GitHub), `@` points inside (your registered catalog).

**`brew install fzf` fails with `no bottle available`** — this happens on macOS pre-release (beta) versions, which Homebrew supports only as Tier 2/3 without prebuilt bottles. Use fzf's official installer instead (downloads a prebuilt binary, no compile):

```bash
git clone --depth 1 https://github.com/junegunn/fzf.git ~/.fzf
~/.fzf/install --bin
ln -sfn ~/.fzf/bin/fzf ~/.local/bin/fzf
```

**`socrates: command not found` right after plugin install** — the CLI links are created by a SessionStart hook, so either start one Claude session, or create them directly without Claude:

```bash
bash ~/.claude/plugins/cache/beret21/socrates/*/bin/socrates doctor --fix
```

## Updates

Updates are manual by default. Commands check GitHub for a newer version at most once a day and append a one-line notice when one exists; `socrates version` always performs a live check. **`socrates update` does everything in one go** — plugin update plus immediate CLI relink, no Claude session needed (manual installs: `git pull`). Versions can be skipped safely (e.g. 0.11 → 0.13): every release is a complete copy, with no migration steps. Run `socrates doctor` before/after updating to verify the environment.

## Versioning

`#.##` — humble by design; 1.0 is far away. The first decimal bumps on structural changes, the second on spec refinements and added checks.

## Environment variables

- `SOC_EXCLUDE` — `grep -E` pattern of working directories to hide from the session list (default: claude-mem observer sessions)

## License

[MIT](LICENSE)
