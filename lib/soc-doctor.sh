#!/bin/bash
# socrates doctor [--fix] — environment health check.
# Verifies dependencies, PATH, install locations, the alias registry, and the version.
# With --fix, repairs missing/broken CLI links (useful right after a plugin
# install, before any Claude session has run the SessionStart hook):
#   bash ~/.claude/plugins/cache/beret21/socrates/*/bin/socrates doctor --fix
# Exit 1 if any ✗ remains.

soc_doctor() {
  local fix=0
  [ "${1:-}" = "--fix" ] && fix=1
  local issues=0 warns=0
  local OK=$'\033[32m✓\033[0m' WARN=$'\033[33m⚠\033[0m' BAD=$'\033[31m✗\033[0m'
  local DIM=$'\033[2m' BOLD=$'\033[1m' RST=$'\033[0m'

  echo ""
  echo "${BOLD}Socrates doctor${RST}"

  # ── Dependencies ───────────────────────────────────────────
  echo ""
  echo "${BOLD}■ Dependencies${RST}"
  for dep in fzf jq; do
    if command -v "$dep" >/dev/null 2>&1; then
      local v
      case "$dep" in
        fzf)     v=$(fzf --version 2>/dev/null | cut -d' ' -f1) ;;
        jq)      v=$(jq --version 2>/dev/null) ;;
      esac
      echo "  $OK $dep ${DIM}($v)${RST}"
    else
      case "$(uname -s)" in
        Darwin)               echo "  $BAD $dep missing — brew install $dep" ;;
        MINGW*|MSYS*|CYGWIN*) echo "  $BAD $dep missing — winget install --id $( [ "$dep" = jq ] && echo jqlang.jq || echo junegunn.fzf ) --source winget, then 'bash install.sh'" ;;
        *)                    echo "  $BAD $dep missing — install via your package manager (e.g. apt install $dep)" ;;
      esac
      if [ "$dep" = "fzf" ] && [ "$(uname -s)" = Darwin ]; then
        echo "    ${DIM}no brew bottle (e.g. macOS beta)? use the official installer:${RST}"
        echo "    ${DIM}git clone --depth 1 https://github.com/junegunn/fzf.git ~/.fzf && ~/.fzf/install --bin && ln -sfn ~/.fzf/bin/fzf ~/.local/bin/fzf${RST}"
      fi
      issues=$((issues+1))
    fi
  done
  # Python: SOC_PY (set by bin/socrates) already excludes the Windows Store stub.
  if [ -n "${SOC_PY:-}" ]; then
    echo "  $OK ${SOC_PY} ${DIM}($("$SOC_PY" --version 2>/dev/null | cut -d' ' -f2))${RST}"
  else
    echo "  $BAD python missing — need a working Python 3"
    echo "    ${DIM}on Windows Git Bash a 'python3' Microsoft Store stub does not count (it exits 49); install real Python and ensure 'python' runs${RST}"
    issues=$((issues+1))
  fi

  # ── PATH ───────────────────────────────────────────────────
  echo ""
  echo "${BOLD}■ PATH${RST}"
  case ":$PATH:" in
    *":$HOME/.local/bin:"*)
      echo "  $OK ~/.local/bin is on PATH" ;;
    *)
      echo "  $BAD ~/.local/bin is NOT on PATH — add to ~/.zshrc:"
      echo "    ${DIM}export PATH=\"\$HOME/.local/bin:\$PATH\"${RST}"
      issues=$((issues+1)) ;;
  esac

  # ── Install locations ──────────────────────────────────────
  echo ""
  echo "${BOLD}■ Install${RST}"
  echo "  ${DIM}running from: $SOC_ROOT${RST}"
  for link in "$HOME/.local/bin/socrates" "$HOME/.local/bin/soc"; do
    if [ -L "$link" ] && [ -e "$link" ]; then
      local target
      target=$(readlink "$link")
      local kind="manual (repo)"
      case "$target" in (*"/plugins/cache/"*) kind="plugin cache";; esac
      echo "  $OK $(basename "$link") → ${DIM}$target${RST} ${DIM}[$kind]${RST}"
    elif [ -e "$link" ] && [ ! -L "$link" ]; then
      # Git Bash without native symlinks: `ln -sfn` silently makes a runnable
      # copy, not a link, so [ -L ] is false even though the CLI works. Treat a
      # runnable file at the link path as OK on Windows rather than warning.
      if [ -n "${MSYSTEM:-}" ] || [ "${OS:-}" = "Windows_NT" ]; then
        echo "  $OK $(basename "$link") ${DIM}(copy — Git Bash has no native symlinks)${RST}"
      else
        echo "  $WARN $(basename "$link") exists but is not a symlink"
        warns=$((warns+1))
      fi
    elif [ "$fix" -eq 1 ]; then
      mkdir -p "$HOME/.local/bin"
      ln -sfn "$SOC_ROOT/bin/socrates" "$link"
      echo "  $OK $(basename "$link") → ${DIM}$SOC_ROOT/bin/socrates${RST} ${DIM}[fixed]${RST}"
    elif [ -L "$link" ]; then
      echo "  $BAD $(basename "$link") is a broken link → $(readlink "$link")"
      echo "    ${DIM}run 'socrates doctor --fix' (or start a Claude session to re-run the hook)${RST}"
      issues=$((issues+1))
    else
      echo "  $WARN $(basename "$link") not installed ${DIM}(start a Claude session, or run doctor --fix)${RST}"
      warns=$((warns+1))
    fi
  done
  # Skill: manual link and/or plugin
  if [ -L "$HOME/.claude/skills/socrates" ]; then
    if [ -e "$HOME/.claude/skills/socrates" ]; then
      echo "  $OK skill (manual): ~/.claude/skills/socrates → ${DIM}$(readlink "$HOME/.claude/skills/socrates")${RST}"
    else
      echo "  $BAD skill link is broken: ~/.claude/skills/socrates"
      issues=$((issues+1))
    fi
  fi
  local plugin_cache
  plugin_cache=$(ls -d "$HOME/.claude/plugins/cache/"*/socrates*/ 2>/dev/null | head -1) || true
  if [ -n "$plugin_cache" ]; then
    echo "  $OK skill (plugin): ${DIM}$plugin_cache${RST}"
  fi
  if [ ! -L "$HOME/.claude/skills/socrates" ] && [ -z "$plugin_cache" ]; then
    echo "  $WARN /socrates skill not installed (plugin or install.sh)"
    warns=$((warns+1))
  fi

  # ── Data / registry ────────────────────────────────────────
  echo ""
  echo "${BOLD}■ Data${RST}"
  local reg="$HOME/.claude/socrates/sessions.json"
  if [ -d "$HOME/.claude/socrates" ] && [ -w "$HOME/.claude/socrates" ]; then
    echo "  $OK data dir writable: ~/.claude/socrates"
  else
    echo "  $WARN data dir missing (created on first use)"
    warns=$((warns+1))
  fi
  if [ -f "$reg" ]; then
    if jq -e . "$reg" >/dev/null 2>&1; then
      local count orphans=0 uuid
      count=$(jq 'length' "$reg")
      echo "  $OK registry valid — $count alias(es)"
      while IFS= read -r uuid; do
        ls "$HOME/.claude/projects/"*"/$uuid.jsonl" >/dev/null 2>&1 || {
          orphans=$((orphans+1))
          echo "  $WARN orphaned alias: $(jq -r --arg id "$uuid" '.[$id].alias' "$reg") ${DIM}(session $uuid no longer exists)${RST}"
        }
      done < <(jq -r 'keys[]' "$reg")
      warns=$((warns+orphans))
    else
      echo "  $BAD registry is not valid JSON: $reg"
      issues=$((issues+1))
    fi
  else
    echo "  ${DIM}· registry not created yet (register with /socrates <alias>)${RST}"
  fi

  # ── Version ────────────────────────────────────────────────
  echo ""
  echo "${BOLD}■ Version${RST}"
  local cur remote
  cur=$(soc_local_version)
  remote=$(soc_remote_version)
  if [ -z "$remote" ]; then
    echo "  $WARN installed $cur — could not reach GitHub to compare"
    warns=$((warns+1))
  elif soc_is_newer "$cur" "$remote"; then
    echo "  $WARN installed $cur, latest $remote — update available"
    echo "    ${DIM}plugin: /plugin update socrates@beret21 · manual: git pull${RST}"
    warns=$((warns+1))
  else
    echo "  $OK installed $cur — up to date"
  fi
  # Refresh the notice cache only if the data dir already exists — doctor must
  # not create it as a side effect (it would contradict the Data report above).
  [ -d "$HOME/.claude/socrates" ] && echo "$(date +%s) ${remote:-}" > "$SOC_UPDATE_CACHE"

  # ── Summary ────────────────────────────────────────────────
  echo ""
  if [ "$issues" -gt 0 ]; then
    echo "${BOLD}Result:${RST} $issues issue(s), $warns warning(s) — see ✗ above"
    return 1
  fi
  echo "${BOLD}Result:${RST} OK — $warns warning(s)"
  return 0
}
