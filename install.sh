#!/bin/bash
# Socrates installer (manual install path)
#  1. symlink ~/.local/bin/socrates (+ short alias soc) → bin/socrates
#  2. symlink ~/.claude/skills/socrates → skills/socrates (/socrates slash command)
#  3. print the zsh wrapper snippet (~/.zshrc is never modified automatically)
# If you install via the plugin, this script is not needed (see README).
# Uninstall:  bash install.sh --uninstall  (add --purge to also delete data)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# OS detection
os_kind() {
  case "$(uname -s)" in
    Darwin)               echo mac ;;
    MINGW*|MSYS*|CYGWIN*) echo windows ;;
    *)                    echo linux ;;
  esac
}

# Uninstall: remove what install.sh created (CLI + skill links). Data under
# ~/.claude/socrates is kept unless --purge is given.
#   bash install.sh --uninstall          # remove links, keep data
#   bash install.sh --uninstall --purge  # also delete session aliases / report
if [ "${1:-}" = "--uninstall" ]; then
  echo "Uninstalling Socrates — $ROOT"
  if [ "$(os_kind)" = windows ]; then win=1; else win=0; fi

  # 1. CLI — remove only if it belongs to THIS repo (a wrapper that execs $ROOT,
  #    or a symlink pointing at it); never touch a plugin-managed link.
  for n in socrates soc; do
    f="$HOME/.local/bin/$n"
    [ -e "$f" ] || [ -L "$f" ] || continue
    if grep -qF "$ROOT/bin/socrates" "$f" 2>/dev/null \
       || [ "$(readlink "$f" 2>/dev/null)" = "$ROOT/bin/socrates" ]; then
      rm -f "$f" && echo "✓ removed ~/.local/bin/$n"
    else
      echo "· skipped ~/.local/bin/$n (not from this install)"
    fi
  done

  # 2. skill links. A junction/symlink must be UNLINKED, never rm -rf'd — rm -rf
  #    follows the link into the repo and deletes the originals. On Windows a
  #    junction is removed with `rmdir` (no /S). A plain directory is an old copy
  #    (stale install) and is safe to recursive-remove.
  for s in socrates-name socrates-status; do
    link="$HOME/.claude/skills/$s"
    if [ -L "$link" ]; then
      if [ "$win" = 1 ]; then
        if MSYS2_ARG_CONV_EXCL='*' cmd.exe /c rmdir "$(cygpath -w "$link")" >/dev/null 2>&1; then
          echo "✓ removed junction ~/.claude/skills/$s"
        else
          echo "⚠ could not remove ~/.claude/skills/$s — run: cmd //c rmdir \"\$(cygpath -w ~/.claude/skills/$s)\""
        fi
      else
        rm -f "$link" && echo "✓ removed link ~/.claude/skills/$s"
      fi
    elif [ -d "$link" ]; then
      rm -rf "$link" && echo "✓ removed copy ~/.claude/skills/$s"
    fi
  done

  # 3. data dir — keep by default
  if [ "${2:-}" = "--purge" ]; then
    rm -rf "$HOME/.claude/socrates" && echo "✓ removed data ~/.claude/socrates"
  elif [ -d "$HOME/.claude/socrates" ]; then
    echo "· kept ~/.claude/socrates (session aliases, report) — remove with --purge"
  fi

  # 4. notes on things install.sh did not exclusively own
  if [ "$win" = 1 ]; then
    echo "· left ~/.local/bin/{fzf,jq}.exe (shared tools) — remove manually if unused."
  fi
  echo "· the repo folder is untouched; delete it from your file sync if desired."
  echo "Done."
  exit 0
fi

echo "Installing Socrates — $ROOT"
echo ""

# winget install helpers
winget_id() {
  case "$1" in
    fzf)            echo junegunn.fzf ;;
    jq)             echo jqlang.jq ;;
    sqlite3)        echo SQLite.SQLite ;;
    python3|python) echo Python.Python.3.12 ;;
    *)              echo "$1" ;;
  esac
}
# On Windows, winget installs portable tools under
# %LOCALAPPDATA%\Microsoft\WinGet\Packages (the documented portablePackageUserRoot)
# and exposes them only as App Execution Alias stubs that MSYS (Git Bash) cannot
# exec. Copy the real .exe onto ~/.local/bin (already on PATH) to fix that.
win_copy_winget() {
  local pkgs found d localapp
  localapp=$(cygpath -u "$LOCALAPPDATA" 2>/dev/null || printf '%s' "${LOCALAPPDATA:-}")
  pkgs="$localapp/Microsoft/WinGet/Packages"
  [ -d "$pkgs" ] || return 0
  mkdir -p "$HOME/.local/bin"
  for d in $1; do
    found=$(ls "$pkgs"/"$(winget_id "$d")"_*/"$d".exe 2>/dev/null | head -1) || true
    [ -n "$found" ] && cp "$found" "$HOME/.local/bin/" \
      && echo "✓ copied $d.exe → ~/.local/bin (winget App-Execution-Alias workaround)"
  done
}

# Dependency check
check_missing() {
  missing=""
  for dep in fzf jq python3; do
    command -v "$dep" >/dev/null 2>&1 || missing="$missing $dep"
  done
}
check_missing
# Windows: try to satisfy fzf/jq from the winget package dir before giving up
if [ -n "$missing" ] && [ "$(os_kind)" = windows ]; then
  win_copy_winget "$missing"
  check_missing
fi
if [ -n "$missing" ]; then
  echo "Missing required tools:$missing"
  case "$(os_kind)" in
    mac)     echo "Install with: brew install$missing" ;;
    windows) printf 'Install with: winget install'
             for d in $missing; do printf ' --id %s --source winget' "$(winget_id "$d")"; done
             printf '\n'
             echo "  then re-run: bash install.sh  (copies the .exe onto PATH for Git Bash)" ;;
    *)       echo "Install with your package manager, e.g.: sudo apt install$missing" ;;
  esac
  exit 1
fi

# 1. socrates command (+ short alias soc)
mkdir -p "$HOME/.local/bin"
if [ "$(os_kind)" = windows ]; then
  # Git Bash has no native symlinks: `ln -sfn` makes a *copy*. But bin/socrates
  # resolves its lib dir by following symlinks back to the repo — a copy is not
  # a link, so SOC_ROOT would collapse to ~/.local and every `source` would
  # fail. Write a wrapper that execs the repo copy instead.
  for name in socrates soc; do
    printf '#!/bin/bash\nexec "%s/bin/socrates" "$@"\n' "$ROOT" > "$HOME/.local/bin/$name"
    chmod +x "$HOME/.local/bin/$name"
  done
  echo "✓ $HOME/.local/bin/socrates → wrapper → $ROOT/bin/socrates (short alias soc included)"
else
  ln -sfn "$ROOT/bin/socrates" "$HOME/.local/bin/socrates"
  ln -sfn "$ROOT/bin/socrates" "$HOME/.local/bin/soc"
  echo "✓ $HOME/.local/bin/socrates → $ROOT/bin/socrates (short alias soc included)"
fi
chmod +x "$ROOT/bin/socrates" "$ROOT/skills/name/socreg.sh"

# 2. skills — manual installs have no plugin namespace, so the link names
#    carry the socrates- prefix: /socrates-name, /socrates-status
mkdir -p "$HOME/.claude/skills"
if [ "$(os_kind)" = windows ]; then
  # Git Bash has no native symlinks: `ln -sfn` deep-copies the directory
  # (stale, won't track repo edits) and is NOT idempotent — a re-run nests
  # socrates-name/name and errors "cannot overwrite directory". Use a junction
  # (mklink /J): no admin/Developer Mode needed, tracks the repo live.
  # MSYS2_ARG_CONV_EXCL stops MSYS from rewriting the /J switch.
  for s in name status; do
    link="$HOME/.claude/skills/socrates-$s"
    rm -rf "$link"
    MSYS2_ARG_CONV_EXCL='*' cmd.exe /c mklink /J \
      "$(cygpath -w "$link")" "$(cygpath -w "$ROOT/skills/$s")" >/dev/null
  done
else
  ln -sfn "$ROOT/skills/name" "$HOME/.claude/skills/socrates-name"
  ln -sfn "$ROOT/skills/status" "$HOME/.claude/skills/socrates-status"
fi
echo "✓ ~/.claude/skills/socrates-name, socrates-status  (/socrates-name, /socrates-status)"

# Clean up legacy skill links if they point into this repo
for legacy in soc socrates; do
  if [ -L "$HOME/.claude/skills/$legacy" ] && [[ "$(readlink "$HOME/.claude/skills/$legacy")" == "$ROOT"* ]]; then
    rm "$HOME/.claude/skills/$legacy"
    echo "✓ removed legacy skill link (~/.claude/skills/$legacy)"
  fi
done

# 3. PATH / wrapper guidance
echo ""
case ":$PATH:" in
  *":$HOME/.local/bin:"*) echo "✓ ~/.local/bin is on your PATH." ;;
  *)
    echo "⚠ ~/.local/bin is not on your PATH. Add this to ~/.zshrc:"
    echo '    export PATH="$HOME/.local/bin:$PATH"'
    ;;
esac

cat <<'EOF'

Optional: to also support 'claude soc list', add this wrapper to ~/.zshrc
(we never modify it for you):

  claude() {
    if [[ "$1" == "soc" ]]; then shift; soc "$@"; else command claude "$@"; fi
  }

Done. Usage: socrates help  (short: soc help)
EOF
