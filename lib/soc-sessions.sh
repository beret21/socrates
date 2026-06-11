#!/bin/bash
# Socrates session scanner + fzf picker
# Session jsonl files under ~/.claude/projects/ are accessed READ-ONLY.
# Writes go only to ~/.claude/socrates/sessions.json via skills/name/socreg.sh.

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

# Column-header row (consumed by fzf --header-lines=1; same field layout as rows)
_soc_header_row() {
  local name_h proj_h
  name_h=$(printf '%-44s' 'NAME (★ = alias)')
  proj_h=$(printf '%-24s' 'PROJECT')
  printf -- '-\t-\t%s%s%s\t%s%s%s\t%s%s%s\t-\n' \
    "$_C_DIM" "$name_h" "$_C_RST" "$_C_DIM" "$proj_h" "$_C_RST" "$_C_DIM" "LAST" "$_C_RST"
}

# Build one TSV row for a session file (or nothing if skipped).
# Fields: 1=uuid  2=jsonl path  3=name  4=project  5=relative time  6=cwd
# Name priority: ★alias → native name (customTitle from -n//rename) → slug → first message
_soc_row() {
  local mtime="$1" jsonl="$2"
  # NOTE: never name a variable 'path' — zsh ties it to PATH
  local uuid alias native cwd slug firstmsg name project rel
  uuid=$(basename "$jsonl" .jsonl)
  case "$uuid" in (*[!0-9a-f-]*) return 0;; esac

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
    return 0
  fi

  # Native session name (claude -n / /rename), stored as customTitle.
  # Renames land late in the transcript, so grep the whole file; last one wins.
  native=$(grep -o '"customTitle":"[^"]*"' "$jsonl" 2>/dev/null | tail -1 \
    | sed 's/^"customTitle":"//; s/"$//') || true

  alias=""
  if [ -f "$SOC_REGISTRY" ]; then
    alias=$(jq -r --arg id "$uuid" '.[$id].alias // ""' "$SOC_REGISTRY" 2>/dev/null) || true
  fi

  if [ -n "$alias" ]; then
    name="${_C_GOLD}★ ${alias}${_C_RST}"
  elif [ -n "$native" ]; then
    name="  ${native}"
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
}

# Build the session list as TSV (most recently modified first, top N)
_soc_scan() {
  local limit="${1:-50}"
  local sorted mtime jsonl
  _soc_header_row
  # Materialize the full sorted list before truncating: piping straight into
  # `head` makes `sort` die of SIGPIPE once the limit is reached, which kills
  # the whole script under `set -o pipefail` (exit 141, no output) whenever
  # there are more sessions than the limit.
  sorted=$(mktemp)
  find "$SOC_PROJECTS_DIR" -maxdepth 2 -name '*.jsonl' -type f -print0 2>/dev/null \
    | xargs -0 stat -f '%m %N' 2>/dev/null \
    | sort -rn > "$sorted" || true

  head -n "$limit" "$sorted" \
    | while read -r mtime jsonl; do
        _soc_row "$mtime" "$jsonl"
      done
  rm -f "$sorted"
}

# fzf preview: session details. Optional $3 = search query → show matching messages.
soc_preview() {
  local uuid="$1" jsonl="$2" query="${3:-}"
  local alias="" cwd="" slug="" branch="" native=""

  if [ -f "$SOC_REGISTRY" ]; then
    alias=$(jq -r --arg id "$uuid" '.[$id].alias // ""' "$SOC_REGISTRY")
  fi
  # Unit separator join — keeps empty fields from shifting (see _soc_row)
  IFS=$'\x1f' read -r cwd slug branch <<< "$(head -n 10 "$jsonl" 2>/dev/null \
    | jq -rs '[([.[]|.cwd? // empty]|first // ""), ([.[]|.slug? // empty]|first // ""), ([.[]|.gitBranch? // empty]|first // "")] | join("\u001f")' 2>/dev/null)"
  native=$(grep -o '"customTitle":"[^"]*"' "$jsonl" 2>/dev/null | tail -1 \
    | sed 's/^"customTitle":"//; s/"$//') || true

  printf '\033[33m%s\033[0m\n' "${alias:-${native:-${slug:-$uuid}}}"
  echo "──────────────────────────────────"
  echo "session : $uuid"
  [ -n "$native" ] && echo "title   : $native (native)"
  echo "project : $cwd"
  echo "branch  : ${branch:--}"
  echo "updated : $(date -r "$(stat -f %m "$jsonl")" '+%Y-%m-%d %H:%M')"
  echo ""

  local msgs
  if [ -n "$query" ]; then
    printf '\033[34mMessages matching: %s\033[0m\n' "$query"
    echo "──────────────────────────────────"
    # Search every string value (dialog, tool output, file paths) so the
    # preview agrees with the grep that matched the file in the first place.
    # Show a window AROUND each match — long strings (e.g. tool output) would
    # otherwise be truncated before the match and filtered out.
    local q_re
    q_re=$(printf '%s' "$query" | sed 's/[.[\*^$\\]/\\&/g')
    msgs=$(jq -r --arg q "$(printf '%s' "$query" | tr '[:upper:]' '[:lower:]')" '
      .. | strings | gsub("[\n\t]"; " ")
      | select(ascii_downcase | contains($q))
    ' "$jsonl" 2>/dev/null \
      | grep -oi -- ".\{0,80\}${q_re}.\{0,80\}" 2>/dev/null \
      | awk '!seen[$0]++' | head -40 \
      | grep --color=always -i -- "$q_re" 2>/dev/null | sed 's/^/· /') || true
  else
    printf '\033[34mRecent user messages\033[0m\n'
    echo "──────────────────────────────────"
    msgs=$(tail -n 300 "$jsonl" 2>/dev/null | jq -r '
      select(.type=="user") | .message.content
      | if type=="string" then .
        elif type=="array" then ([.[] | .text? // empty] | join(" "))
        else empty end
      | gsub("\n"; " ") | .[0:200]
    ' 2>/dev/null | grep -v '^\s*<' | grep -v '^\s*$' | tail -10 | sed 's/^/· /') || true
  fi
  if [ -n "$msgs" ]; then
    printf '%s\n' "$msgs"
  else
    printf '\033[2m(no matching/recent user messages found)\033[0m\n'
  fi
}

# Perform one action on a chosen session: $1=action $2=uuid $3=cwd
_soc_do_action() {
  local action="$1" uuid="$2" cwd="$3"
  case "$action" in
    uuid)
      printf '%s' "$uuid" | pbcopy
      echo "Copied to clipboard: $uuid"
      ;;
    full)
      printf 'cd "%s" && claude --resume %s' "$cwd" "$uuid" | pbcopy
      echo "Copied to clipboard: cd \"$cwd\" && claude --resume $uuid"
      ;;
    name)
      local new_alias
      printf 'Alias for this session: '
      read -r new_alias
      [ -n "$new_alias" ] || { echo "Cancelled"; return 0; }
      new_alias=$(printf '%s' "$new_alias" | tr ' ' '-')
      bash "$SOC_ROOT/skills/name/socreg.sh" "$uuid" "$new_alias" "$cwd"
      ;;
    resume|*)
      printf -- '--resume %s' "$uuid" | pbcopy
      echo "Copied to clipboard: --resume $uuid"
      echo "run : cd \"$cwd\" && claude --resume $uuid"
      echo "note: --resume finds sessions only from their own project folder"
      ;;
  esac
}

# Shared picker: $1=tsv file (row 1 = column header), $2=prompt, $3=header, $4=optional query
# Enter opens an action menu for the chosen session (ESC there returns to the list);
# Ctrl-Y / Ctrl-O / Ctrl-N act immediately.
_soc_pick() {
  local tsv="$1" prompt="$2" header="$3" query="${4:-}"
  local q_esc preview out key sel uuid cwd action
  q_esc=$(printf '%s' "$query" | sed "s/'/'\\\\''/g")
  preview="\"$SOC_ROOT/bin/socrates\" __preview {1} {2}"
  [ -n "$query" ] && preview="$preview '$q_esc'"

  while true; do
    out=$(fzf < "$tsv" \
      --delimiter=$'\t' --with-nth=3,4,5 --ansi --no-sort \
      --header-lines=1 \
      --expect=ctrl-y,ctrl-o,ctrl-n \
      --layout=reverse --info=inline-right \
      --prompt="$prompt" \
      --header="$header" \
      --preview="$preview" \
      --preview-window='right,55%,wrap,<90(down,45%,wrap)' \
      --bind 'ctrl-/:change-preview-window(down,80%,wrap|right,55%,wrap,<90(down,45%,wrap))') || return 0

    key=$(printf '%s\n' "$out" | sed -n 1p)
    sel=$(printf '%s\n' "$out" | sed -n 2p)
    [ -n "$sel" ] || return 0
    uuid=$(printf '%s' "$sel" | cut -f1)
    cwd=$(printf '%s' "$sel" | cut -f6)

    case "$key" in
      ctrl-y) _soc_do_action uuid "$uuid" "$cwd"; return 0;;
      ctrl-o) _soc_do_action full "$uuid" "$cwd"; return 0;;
      ctrl-n) _soc_do_action name "$uuid" "$cwd"; return 0;;
      *)
        # Enter → action menu; ESC there goes back to the session list
        action=$(printf '%s\n' \
          $'resume\tCopy "--resume <UUID>"        (paste after: claude )' \
          $'full\tCopy the full command:        cd "<project>" && claude --resume <UUID>' \
          $'uuid\tCopy the UUID only' \
          $'name\tSet/update this session\x27s alias' \
          $'back\t← Back to the session list' \
          | fzf --delimiter=$'\t' --with-nth=2 --ansi --no-sort \
              --layout=reverse --info=hidden \
              --prompt='action ❯ ' \
              --header="session ${uuid:0:8}… · $(basename "$cwd")  (ESC = back)") || continue
        action=$(printf '%s' "$action" | cut -f1)
        [ "$action" = "back" ] && continue
        _soc_do_action "$action" "$uuid" "$cwd"
        return 0
        ;;
    esac
  done
}

# socrates list — pick with fzf → copy '--resume <UUID>' to the clipboard
soc_list() {
  _soc_require fzf jq
  local tsv
  tsv=$(mktemp)
  _soc_scan "${1:-50}" > "$tsv"
  if [ "$(wc -l < "$tsv")" -le 1 ]; then   # only the column-header row
    echo "No sessions found under: $SOC_PROJECTS_DIR" >&2
    rm -f "$tsv"; return 1
  fi
  _soc_pick "$tsv" 'Socrates ❯ type to search  ' \
    $'Sessions from ALL projects, newest first\nEnter = action menu · Ctrl-O cd+resume · Ctrl-Y UUID · Ctrl-N name\nShift-↑↓ scroll preview · Ctrl-/ big preview · ESC quit'
  rm -f "$tsv"
}

# socrates find <text> — full-text search across ALL session transcripts
soc_find() {
  _soc_require fzf jq
  local query="${1:-}"
  if [ -z "$query" ]; then
    echo "Usage: socrates find <text>" >&2
    echo "Searches the full content of every session transcript on this machine." >&2
    return 1
  fi

  local matches sorted tsv rows f n total
  matches=$(mktemp); sorted=$(mktemp); tsv=$(mktemp); rows=$(mktemp)
  total=$(find "$SOC_PROJECTS_DIR" -maxdepth 2 -name '*.jsonl' -type f 2>/dev/null | wc -l | tr -d ' ')
  echo "Searching $total transcripts for \"$query\"…" >&2

  # Restrict the search to session transcripts only (not other files in the tree)
  find "$SOC_PROJECTS_DIR" -maxdepth 2 -name '*.jsonl' -type f -print0 2>/dev/null \
    | xargs -0 grep -il -- "$query" > "$matches" 2>/dev/null || true
  if [ ! -s "$matches" ]; then
    echo "No sessions matched: $query"
    rm -f "$matches" "$sorted" "$tsv" "$rows"; return 1
  fi
  echo "Found $(wc -l < "$matches" | tr -d ' ') matching session(s), building the list…" >&2

  # newest first
  while read -r f; do
    [ -f "$f" ] && stat -f '%m %N' "$f"
  done < "$matches" | sort -rn > "$sorted"
  while read -r mtime f; do
    _soc_row "$mtime" "$f"
  done < "$sorted" > "$rows"

  n=$(wc -l < "$rows" | tr -d ' ')
  if [ "$n" = "0" ]; then
    echo "No sessions matched: $query"
    rm -f "$matches" "$sorted" "$tsv" "$rows"; return 1
  fi
  { _soc_header_row; cat "$rows"; } > "$tsv"
  _soc_pick "$tsv" "find: $query ❯ " \
    "$n session(s) whose transcript contains \"$query\" — preview shows matches
Enter = action menu · type = narrow further · ESC quit
Shift-↑↓ scroll preview · Ctrl-/ big preview" \
    "$query"
  rm -f "$matches" "$sorted" "$tsv" "$rows"
}

# socrates name [alias] — pick a session, set/update its alias
soc_name() {
  _soc_require fzf jq
  local new_alias="${1:-}" tsv sel uuid cwd
  tsv=$(mktemp)
  _soc_scan 50 > "$tsv"
  if [ "$(wc -l < "$tsv")" -le 1 ]; then   # only the column-header row
    echo "No sessions found." >&2
    rm -f "$tsv"; return 1
  fi

  sel=$(fzf < "$tsv" \
    --delimiter=$'\t' --with-nth=3,4,5 --ansi --no-sort \
    --header-lines=1 \
    --layout=reverse --info=inline-right \
    --prompt='Name which session? ❯ ' \
    --header=$'↑↓ move · type = fuzzy search · Enter: pick · ESC: quit' \
    --preview="\"$SOC_ROOT/bin/socrates\" __preview {1} {2}" \
    --preview-window='right,55%,wrap,<90(down,45%,wrap)') || { rm -f "$tsv"; return 0; }
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
