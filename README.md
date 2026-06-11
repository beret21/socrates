# Socrates — "Know Your Self"

> γνῶθι σεαυτόν — A session & settings manager for Claude Code

**English** | [한국어](README.ko.md)

When you run many Claude Code CLI sessions, two things get hard: (1) finding your way back to the session you were working in after a reboot, and (2) understanding what is actually configured across `~/.claude/` and per-project `.claude/` directories (hooks, plugins, MCP servers, skills, agents). Socrates solves both.

> **Platform**: macOS only for now (uses `pbcopy`, `open`, BSD `stat`). Linux/WSL and native Windows support are on the roadmap.

![socrates list — fzf session picker](assets/terminal-picker.png)
*`socrates list`: every session on the machine, aliased ones starred; Enter opens an action menu that copies `--resume <UUID>`. (All screenshots use synthetic demo data.)*

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

![/socrates:name inside a Claude session](assets/terminal-skill.png)

(With the manual install the commands are `/socrates-name` and `/socrates-status`.)

### In the terminal — `socrates` (short alias: `soc`)

| Command | What it does |
|---------|--------------|
| `socrates` / `socrates list` | fzf session picker. **Enter → action menu**; **Ctrl-Y/Ctrl-O copy without leaving the picker** (copy `--resume` / copy full `cd … && claude --resume …` / copy UUID / set alias / back); shortcuts: **Ctrl-P narrows to the highlighted session's project**, Ctrl-O cd+resume, Ctrl-Y UUID, Ctrl-N name. Ctrl-U/D scrolls the preview, Ctrl-T enlarges it |
| `socrates projects` | two-stage navigation grouped by project (the storage folder is the group key — instant summary with session counts, ★ aliases, last activity); Enter opens that project's sessions, ESC goes back |
| `socrates find <text>` | **full-text search across every session transcript** on this machine — something the native picker cannot do. Matches open in the same picker, with matching snippets highlighted in the preview |
| `socrates name [alias]` | pick a session and set/update its alias |
| `socrates unname` | pick an alias and remove it (the session itself is untouched) |
| `socrates mem <text|id>` | read-only search of what the claude-mem plugin remembers about you; an id prints the full stored record **plus the official removal steps** (identification → guidance; Socrates never deletes) |
| `socrates map` | print the settings hierarchy, hooks, plugins, MCP servers, and skills/agents inventory |
| `socrates report` | generate a tabbed HTML dashboard (Overview / Projects / Sessions / **Config X-ray** / **Memory & Identity** / **Injection** / Harness, with an **EN/한국어 toggle**) and open it. Memory & Identity shows how Claude identifies you (local `~/.claude.json` account info) and every project's auto-memory files with their descriptions. The X-ray shows, per project, the settings layers and the full **CLAUDE.md chain** — every memory file a new session would load, walking from the filesystem root down to the project ([official rule](https://code.claude.com/docs/en/memory#how-claude-md-files-load)), with sizes and ancestor-folder warnings |
| `socrates update` | update everything from the terminal: plugin (skill + CLI) and relink — no Claude session needed. Manual installs do `git pull` |
| `socrates doctor [--fix]` | check the environment: dependencies, PATH, install links, registry integrity, orphaned aliases, version. `--fix` repairs missing/broken CLI links |
| `socrates version` | print the installed version and check GitHub for updates |

![socrates map](assets/terminal-map.png)
*`socrates map`: global settings, the CLAUDE.md chain for the current directory, and recent projects at a glance.*

![Config X-ray tab](assets/dashboard-t-xray.png)
*`socrates report` → Config X-ray: per project, the settings layers and every CLAUDE.md file a new session would load — ancestor-folder injections highlighted.*

![Injection tab](assets/dashboard-t-inj.png)
*Injection tab: what third-party memory (claude-mem, hooks) puts into your sessions, and a browser over everything it remembers.*

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

### Moving sessions between Desktop and CLI (verified empirically)

Transcripts live in one shared store (`~/.claude/projects/`), so sessions cross frontends — but titles and sidebar lists are per-frontend:

| Direction | How | Carries |
|-----------|-----|---------|
| Desktop → CLI | `socrates list`/`find` → copy → `cd "<project>" && claude --resume <UUID>` | full conversation ✓ |
| CLI → Desktop | inside the CLI session: send **at least one message first**, then `/desktop` | full conversation ✓ — but the native name (`customTitle`) is not shown as the Desktop title |
| CLI session in the Desktop sidebar (without `/desktop`) | not supported — Desktop and CLI keep separate session lists | use `/desktop` to hand off |

## Troubleshooting

**`Plugin "socrates" not found in marketplace "beret21"`** — the marketplace is not registered on this machine yet. Installation is always two steps: `claude plugin marketplace add beret21/socrates` first, then `claude plugin install socrates@beret21`.

**`Plugin "socrates/beret21" not found`** — separator mix-up. `/` is only for the GitHub coordinate in `marketplace add beret21/socrates` (owner/repo); every install/update/uninstall uses `@`: `socrates@beret21` (plugin@marketplace). Rule of thumb: `/` points outside (GitHub), `@` points inside (your registered catalog).

**`brew install fzf` fails with `no bottle available`** — this happens on macOS pre-release (beta) versions, which Homebrew supports only as Tier 2/3 without prebuilt bottles. Use fzf's official installer instead (downloads a prebuilt binary, no compile):

```bash
git clone --depth 1 https://github.com/junegunn/fzf.git ~/.fzf
~/.fzf/install --bin
ln -sfn ~/.fzf/bin/fzf ~/.local/bin/fzf
```

**`claude -n <name>` seems to do nothing / `/desktop` says "transcript not found"** — Claude Code creates the transcript file only after the **first real message** of a session. If you quit (or run `/desktop`) before sending anything, there is no transcript yet, so nothing gets named and Desktop has nothing to open. Send one message first.

**`socrates: command not found` right after plugin install** — the CLI links are created by a SessionStart hook, so either start one Claude session, or create them directly without Claude:

```bash
bash ~/.claude/plugins/cache/beret21/socrates/*/bin/socrates doctor --fix
```

## Updates

Updates are manual by default. Commands check GitHub for a newer version at most once a day and append a one-line notice when one exists; `socrates version` always performs a live check. **`socrates update` does everything in one go** — plugin update plus immediate CLI relink, no Claude session needed (manual installs: `git pull`). Versions can be skipped safely (e.g. 0.11 → 0.13): every release is a complete copy, with no migration steps. Run `socrates doctor` before/after updating to verify the environment.

## Versioning

`0.FEATURE.BUILD` — humble by design; 1.0 is far away. The middle number moves only on major feature units (slowly); the build number increments freely with every fix and refinement (up to 999 per feature unit). Pre-release history note: numbers up to 0.34.0 predate this scheme; re-baselined once to 0.3.0 before public promotion (manual reinstall on the only two installed machines).

## Environment variables

- `SOC_EXCLUDE` — `grep -E` pattern of working directories to hide from the session list (default: claude-mem observer sessions)

## License

[MIT](LICENSE)
