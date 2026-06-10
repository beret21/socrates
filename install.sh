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
chmod +x "$ROOT/bin/socrates" "$ROOT/skills/socrates/socreg.sh"
echo "✓ $HOME/.local/bin/socrates → $ROOT/bin/socrates (short alias soc included)"

# 2. /socrates skill
mkdir -p "$HOME/.claude/skills"
ln -sfn "$ROOT/skills/socrates" "$HOME/.claude/skills/socrates"
echo "✓ ~/.claude/skills/socrates → $ROOT/skills/socrates  (/socrates slash command)"

# Clean up a legacy /soc skill link if it points into this repo
if [ -L "$HOME/.claude/skills/soc" ] && [[ "$(readlink "$HOME/.claude/skills/soc")" == "$ROOT"* ]]; then
  rm "$HOME/.claude/skills/soc"
  echo "✓ removed legacy skill link (~/.claude/skills/soc)"
fi

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
