#!/bin/bash
# socrates doctor — environment health check.
# Verifies dependencies, install locations, the alias registry, and the version.
# Read-only except for the update-check cache. Exit 1 if any ✗ is found.

soc_doctor() {
  local issues=0 warns=0
  local OK=$'\033[32m✓\033[0m' WARN=$'\033[33m⚠\033[0m' BAD=$'\033[31m✗\033[0m'
  local DIM=$'\033[2m' BOLD=$'\033[1m' RST=$'\033[0m'

  echo ""
  echo "${BOLD}Socrates doctor${RST}"

  # ── Dependencies ───────────────────────────────────────────
  echo ""
  echo "${BOLD}■ Dependencies${RST}"
  for dep in fzf jq python3; do
    if command -v "$dep" >/dev/null 2>&1; then
      local v
      case "$dep" in
        fzf)     v=$(fzf --version 2>/dev/null | cut -d' ' -f1) ;;
        jq)      v=$(jq --version 2>/dev/null) ;;
        python3) v=$(python3 --version 2>/dev/null | cut -d' ' -f2) ;;
      esac
      echo "  $OK $dep ${DIM}($v)${RST}"
    else
      echo "  $BAD $dep missing — brew install $dep"
      issues=$((issues+1))
    fi
  done

  # ── Install locations ──────────────────────────────────────
  echo ""
  echo "${BOLD}■ Install${RST}"
  echo "  ${DIM}running from: $SOC_ROOT${RST}"
  for link in "$HOME/.local/bin/socrates" "$HOME/.local/bin/soc"; do
    if [ -L "$link" ]; then
      local target
      target=$(readlink "$link")
      if [ -e "$link" ]; then
        local kind="manual (repo)"
        case "$target" in (*"/plugins/cache/"*) kind="plugin cache";; esac
        echo "  $OK $(basename "$link") → ${DIM}$target${RST} ${DIM}[$kind]${RST}"
      else
        echo "  $BAD $(basename "$link") is a broken link → $target"
        issues=$((issues+1))
      fi
    elif [ -e "$link" ]; then
      echo "  $WARN $(basename "$link") exists but is not a symlink"
      warns=$((warns+1))
    else
      echo "  $WARN $(basename "$link") not installed ${DIM}(plugin SessionStart hook creates it on next session)${RST}"
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
  mkdir -p "$HOME/.claude/socrates"; echo "$(date +%s) ${remote:-}" > "$SOC_UPDATE_CACHE"

  # ── Summary ────────────────────────────────────────────────
  echo ""
  if [ "$issues" -gt 0 ]; then
    echo "${BOLD}Result:${RST} $issues issue(s), $warns warning(s) — see ✗ above"
    return 1
  fi
  echo "${BOLD}Result:${RST} OK — $warns warning(s)"
  return 0
}
