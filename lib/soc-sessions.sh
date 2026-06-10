#!/bin/bash
# Socrates session scanner + fzf picker
# Session jsonl files under ~/.claude/projects/ are accessed READ-ONLY.
# Writes go only to ~/.claude/socrates/sessions.json via skills/socrates/socreg.sh.

SOC_PROJECTS_DIR="$HOME/.claude/projects"
SOC_REGISTRY="$HOME/.claude/socrates/sessions.json"
# cwd patterns to hide from the list (grep -E). Background sessions such as claude-mem observers.
SOC_EXCLUDE="${SOC_EXCLUDE:-claude-mem/observer-sessions|/observer-sessions}"

# Colors (for fzf --ansi)
_C_GOLD=$'\033[33m'
_C_BLUE=$'\033[34m'
_C_DIM=$'\033[2m'
_C_RST=$'\033[0m'

_soc_require() {
  local missing=""
  for dep in "$@"; do
    command -v "$dep" >/dev/null 2>&1 || missing="$missing $dep"
  done
  if [ -n "$missing" ]; then
    echo "Missing required tools:$missing" >&2
    echo "Install with: brew install$missing" >&2
    exit 1
  fi
}

# Render an epoch diff as "3m ago" etc.
_soc_reltime() {
  local diff=$(( $(date +%s) - $1 ))
  if   [ "$diff" -lt 60 ];     then echo "${diff}s ago"
  elif [ "$diff" -lt 3600 ];   then echo "$(( diff / 60 ))m ago"
  elif [ "$diff" -lt 86400 ];  then echo "$(( diff / 3600 ))h ago"
  else                              echo "$(( diff / 86400 ))d ago"
  fi
}

# Build the session list as TSV (most recently modified first, top N)
# Fields: 1=uuid  2=jsonl path  3=name(★alias|slug)  4=project  5=relative time  6=cwd
_soc_scan() {
  local limit="${1:-50}"
  # NOTE: never name a variable 'path' — zsh ties it to PATH
  local alias_map mtime jsonl uuid alias cwd slug firstmsg name project rel
  alias_map=$(mktemp)
  if [ -f "$SOC_REGISTRY" ]; then
    jq -r 'to_entries[] | "\(.key)\t\(.value.alias)"' "$SOC_REGISTRY" > "$alias_map"
  fi

  find "$SOC_PROJECTS_DIR" -maxdepth 2 -name '*.jsonl' -type f -print0 2>/dev/null \
    | xargs -0 stat -f '%m %N' 2>/dev/null \
    | sort -rn | head -n "$limit" \
    | while read -r mtime jsonl; do
        uuid=$(basename "$jsonl" .jsonl)
        case "$uuid" in (*[!0-9a-f-]*) continue;; esac

        # Extract cwd/slug/first user message from the head only (large-file safe).
        # Join with the unit separator (\x1f): unlike tabs, bash `read` does not
        # collapse consecutive non-whitespace delimiters, so empty fields survive.
        IFS=$'\x1f' read -r cwd slug firstmsg <<< "$(head -n 60 "$jsonl" 2>/dev/null \
          | jq -rs '[
              ([.[]|.cwd? // empty] | first // ""),
              ([.[]|.slug? // empty] | first // ""),
              ([.[] | select(.type? == "user") | .message.content?
                 | if type=="string" then . elif type=="array" then ([.[]|.text? // empty]|join(" ")) else empty end
                 | gsub("[\n\t]"; " ") | select(startswith("<") | not) | select(. != "")
               ] | first // "" | .[0:60])
            ] | join("\u001f")' 2>/dev/null)"

        # Skip background/observer sessions
        if [ -n "$SOC_EXCLUDE" ] && printf '%s' "$cwd" | grep -qE "$SOC_EXCLUDE"; then
          continue
        fi

        alias=$(grep -m1 "^${uuid}$(printf '\t')" "$alias_map" 2>/dev/null | cut -f2) || true
        if [ -n "$alias" ]; then
          name="${_C_GOLD}★ ${alias}${_C_RST}"
        elif [ -n "$slug" ]; then
          name="  ${slug}"
        elif [ -n "$firstmsg" ]; then
          name="  ${firstmsg:0:42}"
        else
          name="  ${_C_DIM}${uuid:0:8}${_C_RST}"
        fi
        project=$(basename "${cwd:-?}")
        rel=$(_soc_reltime "$mtime")

        printf '%s\t%s\t%-44s\t%s%-24s%s\t%s%s%s\t%s\n' \
          "$uuid" "$jsonl" "$name" "$_C_BLUE" "$project" "$_C_RST" "$_C_DIM" "$rel" "$_C_RST" "$cwd"
      done
  rm -f "$alias_map"
}

# fzf preview: session details
soc_preview() {
  local uuid="$1" jsonl="$2"
  local alias="" cwd="" slug="" branch=""

  if [ -f "$SOC_REGISTRY" ]; then
    alias=$(jq -r --arg id "$uuid" '.[$id].alias // ""' "$SOC_REGISTRY")
  fi
  # Unit separator join — keeps empty fields from shifting (see _soc_scan)
  IFS=$'\x1f' read -r cwd slug branch <<< "$(head -n 10 "$jsonl" 2>/dev/null \
    | jq -rs '[([.[]|.cwd? // empty]|first // ""), ([.[]|.slug? // empty]|first // ""), ([.[]|.gitBranch? // empty]|first // "")] | join("\u001f")' 2>/dev/null)"

  printf '\033[33m%s\033[0m\n' "${alias:-${slug:-$uuid}}"
  echo "──────────────────────────────────"
  echo "session : $uuid"
  echo "project : $cwd"
  echo "branch  : ${branch:--}"
  echo "updated : $(date -r "$(stat -f %m "$jsonl")" '+%Y-%m-%d %H:%M')"
  echo ""
  printf '\033[34mRecent user messages\033[0m\n'
  echo "──────────────────────────────────"
  local msgs
  msgs=$(tail -n 300 "$jsonl" 2>/dev/null | jq -r '
    select(.type=="user") | .message.content
    | if type=="string" then .
      elif type=="array" then ([.[] | .text? // empty] | join(" "))
      else empty end
    | gsub("\n"; " ") | .[0:200]
  ' 2>/dev/null | grep -v '^\s*<' | grep -v '^\s*$' | tail -5 | sed 's/^/· /')
  if [ -n "$msgs" ]; then
    printf '%s\n' "$msgs"
  else
    printf '\033[2m(no user messages in the recent part of this transcript)\033[0m\n'
  fi
}

# socrates list — pick with fzf → copy '--resume <UUID>' to the clipboard
soc_list() {
  _soc_require fzf jq
  local tsv out key sel uuid cwd
  tsv=$(mktemp)
  _soc_scan "${1:-50}" > "$tsv"
  if [ ! -s "$tsv" ]; then
    echo "No sessions found under: $SOC_PROJECTS_DIR" >&2
    rm -f "$tsv"; return 1
  fi

  out=$(fzf < "$tsv" \
    --delimiter=$'\t' --with-nth=3,4,5 --ansi --no-sort \
    --expect=ctrl-y,ctrl-o,ctrl-n \
    --layout=reverse --info=inline-right \
    --prompt='Socrates ❯ type to search  ' \
    --header=$'┌ Sessions from ALL projects, newest first (★ = aliased)\n│ ↑↓ move · type = fuzzy search · ESC quit\n└ Enter: copy "--resume <UUID>" · Ctrl-O: full cd+resume cmd · Ctrl-Y: UUID · Ctrl-N: name' \
    --preview="\"$SOC_ROOT/bin/socrates\" __preview {1} {2}" \
    --preview-window=right,55%,wrap) || { rm -f "$tsv"; return 0; }
  rm -f "$tsv"

  key=$(printf '%s\n' "$out" | sed -n 1p)
  sel=$(printf '%s\n' "$out" | sed -n 2p)
  [ -n "$sel" ] || return 0
  uuid=$(printf '%s' "$sel" | cut -f1)
  cwd=$(printf '%s' "$sel" | cut -f6)

  case "$key" in
    ctrl-y)
      printf '%s' "$uuid" | pbcopy
      echo "Copied to clipboard: $uuid"
      ;;
    ctrl-o)
      printf 'cd "%s" && claude --resume %s' "$cwd" "$uuid" | pbcopy
      echo "Copied to clipboard: cd \"$cwd\" && claude --resume $uuid"
      ;;
    ctrl-n)
      local new_alias
      printf 'Alias for this session: '
      read -r new_alias
      [ -n "$new_alias" ] || { echo "Cancelled"; return 0; }
      new_alias=$(printf '%s' "$new_alias" | tr ' ' '-')
      bash "$SOC_ROOT/skills/name/socreg.sh" "$uuid" "$new_alias" "$cwd"
      ;;
    *)
      printf -- '--resume %s' "$uuid" | pbcopy
      echo "Copied to clipboard: --resume $uuid"
      echo "run : cd \"$cwd\" && claude --resume $uuid"
      echo "note: --resume finds sessions only from their own project folder (Ctrl-O copies the full command)"
      ;;
  esac
}

# socrates name [alias] — pick a session, set/update its alias
soc_name() {
  _soc_require fzf jq
  local new_alias="${1:-}" tsv sel uuid cwd
  tsv=$(mktemp)
  _soc_scan 50 > "$tsv"
  if [ ! -s "$tsv" ]; then
    echo "No sessions found." >&2
    rm -f "$tsv"; return 1
  fi

  sel=$(fzf < "$tsv" \
    --delimiter=$'\t' --with-nth=3,4,5 --ansi --no-sort \
    --layout=reverse --info=inline-right \
    --prompt='Name which session? ❯ ' \
    --header=$'↑↓ move · type = fuzzy search · Enter: pick · ESC: quit' \
    --preview="\"$SOC_ROOT/bin/socrates\" __preview {1} {2}" \
    --preview-window=right,55%,wrap) || { rm -f "$tsv"; return 0; }
  rm -f "$tsv"
  [ -n "$sel" ] || return 0
  uuid=$(printf '%s' "$sel" | cut -f1)
  cwd=$(printf '%s' "$sel" | cut -f6)

  if [ -z "$new_alias" ]; then
    printf 'Alias: '
    read -r new_alias
    [ -n "$new_alias" ] || { echo "Cancelled"; return 0; }
  fi
  new_alias=$(printf '%s' "$new_alias" | tr ' ' '-')

  bash "$SOC_ROOT/skills/name/socreg.sh" "$uuid" "$new_alias" "$cwd"
}

# socrates unname — pick an aliased session and remove its alias
soc_unname() {
  _soc_require fzf jq
  if [ ! -f "$SOC_REGISTRY" ] || [ "$(jq 'length' "$SOC_REGISTRY" 2>/dev/null || echo 0)" = "0" ]; then
    echo "No aliases registered."
    return 0
  fi
  local sel uuid
  sel=$(jq -r 'to_entries[] | [.key, .value.alias, (.value.cwd | sub(env.HOME; "~"))] | @tsv' "$SOC_REGISTRY" \
    | fzf --delimiter=$'\t' --with-nth=2,3 --layout=reverse --info=inline-right \
        --prompt='Remove which alias? ❯ ' \
        --header=$'Enter: remove the alias (the session itself is NOT deleted) · ESC: quit') || return 0
  [ -n "$sel" ] || return 0
  uuid=$(printf '%s' "$sel" | cut -f1)
  bash "$SOC_ROOT/skills/name/socreg.sh" "$uuid" --delete
}
