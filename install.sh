#!/bin/bash
# Socrates installer (manual install path)
#  1. symlink ~/.local/bin/socrates (+ short alias soc) → bin/socrates
#  2. symlink ~/.claude/skills/socrates → skills/socrates (/socrates slash command)
#  3. print the zsh wrapper snippet (~/.zshrc is never modified automatically)
# If you install via the plugin, this script is not needed (see README).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing Socrates — $ROOT"
echo ""

# OS detection + install hints
os_kind() {
  case "$(uname -s)" in
    Darwin)               echo mac ;;
    MINGW*|MSYS*|CYGWIN*) echo windows ;;
    *)                    echo linux ;;
  esac
}
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
ln -sfn "$ROOT/bin/socrates" "$HOME/.local/bin/socrates"
ln -sfn "$ROOT/bin/socrates" "$HOME/.local/bin/soc"
chmod +x "$ROOT/bin/socrates" "$ROOT/skills/name/socreg.sh"
echo "✓ $HOME/.local/bin/socrates → $ROOT/bin/socrates (short alias soc included)"

# 2. skills — manual installs have no plugin namespace, so the link names
#    carry the socrates- prefix: /socrates-name, /socrates-status
mkdir -p "$HOME/.claude/skills"
ln -sfn "$ROOT/skills/name" "$HOME/.claude/skills/socrates-name"
ln -sfn "$ROOT/skills/status" "$HOME/.claude/skills/socrates-status"
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
