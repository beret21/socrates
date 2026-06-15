# Windows compatibility checklist

Socrates currently targets **macOS** (the README says so). This is a standard
cross-platform QA pass for running it on **Windows** and recording what needs
porting. Work through it top to bottom and fill in the results template at the
end. Nothing here changes code — it only observes behaviour and notes the gaps.

Safety: session transcripts under `~/.claude/projects/` are read-only. Socrates
only writes under `~/.claude/socrates/`. Do not edit anything under
`~/.claude/projects/`.

---

## 1. Record the environment

Note these at the top of your report:

- Windows version (`winver`)
- Shell you are testing in. Socrates is pure `bash`, so a POSIX shell is
  required — **native PowerShell/CMD cannot run it**. (Windows Terminal is just
  the window; pick a *shell* inside it.)
  - **Recommended: Git Bash** — ships with Git for Windows, no WSL needed, and
    it exercises the real *Windows* path (clip.exe / start boundaries). Use this
    first.
  - WSL is optional and only worth it later to also check the Linux port; it is
    effectively Linux, not Windows. If you use it, note the distro.
  - Record which shell you used — results differ between them.
- `bash --version`
- Path to the repo after checkout.

## 2. Prerequisites

Socrates needs `bash`, `fzf`, `jq`, `python3`, plus coreutils (`find`, `head`,
`tail`, `sort`, `grep`, `sed`, `awk`, `xargs`, `mktemp`, `stat`, `date`).

Install and record versions:

- **Git Bash**: `fzf`/`jq` via `winget install fzf` / `winget install jqlang.jq`
  (or `scoop install fzf jq`); Python via `winget install Python.Python.3.12`.
  Note whether the interpreter is `python` or `python3` on PATH.
- **WSL**: `sudo apt install fzf jq python3`.

Record: `fzf --version`, `jq --version`, `python3 --version` (or `python --version`).

## 3. Get the code

Either clone fresh or use the synced copy:

```bash
git clone https://github.com/beret21/socrates.git
cd socrates
```

Make the entry point runnable and check it parses:

```bash
bash -n bin/socrates && echo "syntax ok"
bash bin/socrates help
```

## 4. Platform-specific points to verify

These lines use macOS/BSD-only tools. They are correct on macOS; the task is to
confirm how each behaves on Windows and note the substitute. **This is the core
of the report.**

| File:line | Uses | macOS behaviour | Windows substitute to note |
|-----------|------|-----------------|----------------------------|
| `lib/soc_report.py:1566` | `subprocess.run(["open", …])` | opens the HTML report | `start ""`/`cmd /c start`; WSL `wslview` or `xdg-open` |
| `lib/soc-sessions.sh:152,335,386,428` | `stat -f '%m %N'` / `stat -f %m` (BSD) | mtime + name | GNU `stat -c '%Y %n'` / `stat -c %Y` (Git Bash & WSL ship GNU stat) |
| `lib/soc-sessions.sh:182` | `date -r <epoch>` (BSD) | format a timestamp | GNU `date -d @<epoch>` |
| `lib/soc-sessions.sh:225,229,241,274,275` | `pbcopy` | copy to clipboard | `clip.exe` (Git Bash & WSL can call it); PowerShell `Set-Clipboard` |
| `bin/socrates` (update branch) | `ln -sfn` into `~/.local/bin` | symlink the CLI | Windows symlinks need Developer Mode or admin; note if it fails |
| `hooks/hooks.json` | `ln -sfn` at SessionStart | links CLI on session start | same symlink caveat |

Also confirm the data root resolves: Socrates reads `~/.claude/projects/`.
On Git Bash/WSL `~` should map to the Windows user profile (or the WSL home).
Record what `echo $HOME` and `ls ~/.claude` show.

## 5. Per-command checks

Run each and record **PASS / PARTIAL / FAIL** with the exact output or error.

1. `socrates version` — prints version; checks GitHub. *(network; uses `curl`)*
2. `socrates doctor` — lists dependencies, PATH, install links, registry,
   version. *(good first signal of what is missing)*
3. `socrates map` — prints settings + the CLAUDE.md chain + recent projects.
   *(uses BSD `stat`/`date` via the report module's terminal path — watch for
   wrong/blank timestamps)*
4. `socrates report` — generates the HTML dashboard and tries to open it.
   *(the file should still be written even if `open` fails — check
   `~/.claude/socrates/report.html` exists and renders in a browser manually)*
5. `socrates list` — the fzf picker. *(requires `fzf`; Enter→action menu;
   Ctrl-Y/Ctrl-O copy via `pbcopy` — expect the copy to fail on Windows)*
6. `socrates projects` — two-stage picker.
7. `socrates find socrates` — full-text search across transcripts.
8. `socrates mem <word>` — read-only claude-mem search *(needs `sqlite3`)*.

For the picker commands, if `fzf` works but clipboard copy fails, that is
**PARTIAL** — note that the list/preview render but copy is the broken part.

## 6. Skills (inside Claude on Windows, optional)

If you run the Claude CLI on Windows: `/socrates:name test-win` then
`/socrates:status`. Record whether the alias is written to
`~/.claude/socrates/sessions.json`.

## 7. Write the results document

Create **`docs/WINDOWS-TEST-RESULT.md`** in the repo with this structure:

```markdown
# Windows test result — <date>

## Environment
- Windows: …   Shell: Git Bash | WSL(<distro>)   bash: …
- fzf: …  jq: …  python: …  sqlite3: …

## Command results
| Command | Result | Notes / exact error |
|---------|--------|---------------------|
| version | PASS/PARTIAL/FAIL | … |
| doctor  | … | … |
| map     | … | … |
| report  | … | … |
| list    | … | … |
| projects| … | … |
| find    | … | … |
| mem     | … | … |

## Platform gaps found
For each broken spot: the file:line, the exact symptom, the macOS tool
involved, and the smallest substitute that would fix it (e.g. "replace
`stat -f %m` with an OS-detected `stat -c %Y`").

## Windows prerequisites & environment checks
A key deliverable. Note the split: `socrates doctor` is itself a bash script, so
it can only run **once bash already exists** — it cannot check for bash's
presence (chicken-and-egg). So divide the responsibility:

- **Before bash (cannot be doctor's job)** — list the prerequisites a Windows
  user needs to even start: Git Bash installed; `fzf`/`jq`/`python` on PATH.
  Note where this belongs: the install guide (for a human) and/or a future
  native bootstrap (`install.ps1` / `.cmd`) that detects a missing bash and says
  "install Git for Windows". Give the exact install commands that worked.
- **Inside bash (doctor can do this)** — what `socrates doctor` should
  additionally check on Windows so it warns instead of failing silently: which
  bash flavour it is in (Git Bash / WSL / MSYS); whether a clipboard command is
  reachable (`clip.exe`); whether the report can be opened (`start`). Phrase each
  as a concrete check + the message it should print.

Note for the report: if installation needs a non-bash entry point at all
(because the SessionStart hook also links via bash), say so — it signals the
real porting scope.

## Suggested porting priority
1. … (highest-impact, smallest change first)
2. …

## Overall verdict
Does it run at all? On Git Bash vs WSL? What is the single biggest blocker?
```

Keep it factual: paste real output, not paraphrase. When done, this file syncs
back (or is shared) so the macOS side can plan the port.
