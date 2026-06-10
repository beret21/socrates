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

# Dependency check
missing=""
for dep in fzf jq python3; do
  command -v "$dep" >/dev/null 2>&1 || missing="$missing $dep"
done
if [ -n "$missing" ]; then
  echo "Missing required tools:$missing"
  echo "Install with: brew install$missing"
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
