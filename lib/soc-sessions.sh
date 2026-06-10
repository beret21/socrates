#!/bin/bash
# Socrates 세션 스캔 + fzf 선택기
# ~/.claude/projects/ 의 세션 jsonl은 읽기 전용으로만 접근한다.
# 쓰기는 skills/soc/socreg.sh 를 통해 ~/.claude/socrates/sessions.json 에만 한다.

SOC_PROJECTS_DIR="$HOME/.claude/projects"
SOC_REGISTRY="$HOME/.claude/socrates/sessions.json"
# 목록에서 제외할 cwd 패턴 (grep -E). claude-mem observer 등 백그라운드 세션
SOC_EXCLUDE="${SOC_EXCLUDE:-claude-mem/observer-sessions|/observer-sessions}"

# 색상 (fzf --ansi 용)
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
    echo "필요한 도구가 없습니다:$missing" >&2
    echo "설치: brew install$missing" >&2
    exit 1
  fi
}

# epoch 차이를 "3분 전" 형태로
_soc_reltime() {
  local diff=$(( $(date +%s) - $1 ))
  if   [ "$diff" -lt 60 ];     then echo "${diff}초 전"
  elif [ "$diff" -lt 3600 ];   then echo "$(( diff / 60 ))분 전"
  elif [ "$diff" -lt 86400 ];  then echo "$(( diff / 3600 ))시간 전"
  else                              echo "$(( diff / 86400 ))일 전"
  fi
}

# 세션 목록 TSV 생성 (최근 수정순 상위 N개)
# 필드: 1=uuid  2=jsonl경로  3=이름(★alias|slug)  4=프로젝트  5=상대시각  6=cwd
_soc_scan() {
  local limit="${1:-50}"
  # 주의: 변수명 'path'는 zsh에서 PATH와 연동되는 특수 변수라 사용 금지
  local alias_map mtime jsonl uuid alias cwd slug name project rel
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

        # 첫 줄들에서 cwd/slug/첫 사용자 메시지 추출 (대용량 파일 대비 head만 읽음)
        IFS=$'\t' read -r cwd slug firstmsg <<< "$(head -n 60 "$jsonl" 2>/dev/null \
          | jq -rs '[
              ([.[]|.cwd? // empty] | first // ""),
              ([.[]|.slug? // empty] | first // ""),
              ([.[] | select(.type? == "user") | .message.content?
                 | if type=="string" then . elif type=="array" then ([.[]|.text? // empty]|join(" ")) else empty end
                 | gsub("[\n\t]"; " ") | select(startswith("<") | not) | select(. != "")
               ] | first // "" | .[0:60])
            ] | @tsv' 2>/dev/null)"

        # 백그라운드/관찰자 세션 제외
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

# fzf preview: 세션 상세 정보
soc_preview() {
  local uuid="$1" jsonl="$2"
  local alias="" cwd="" slug="" branch=""

  if [ -f "$SOC_REGISTRY" ]; then
    alias=$(jq -r --arg id "$uuid" '.[$id].alias // ""' "$SOC_REGISTRY")
  fi
  IFS=$'\t' read -r cwd slug branch <<< "$(head -n 10 "$jsonl" 2>/dev/null \
    | jq -rs '[([.[]|.cwd? // empty]|first // ""), ([.[]|.slug? // empty]|first // ""), ([.[]|.gitBranch? // empty]|first // "")] | @tsv' 2>/dev/null)"

  printf '\033[33m%s\033[0m\n' "${alias:-${slug:-$uuid}}"
  echo "──────────────────────────────────"
  echo "session : $uuid"
  echo "project : $cwd"
  echo "branch  : ${branch:--}"
  echo "updated : $(date -r "$(stat -f %m "$jsonl")" '+%Y-%m-%d %H:%M')"
  echo ""
  printf '\033[34m최근 사용자 메시지\033[0m\n'
  echo "──────────────────────────────────"
  tail -n 300 "$jsonl" 2>/dev/null | jq -r '
    select(.type=="user") | .message.content
    | if type=="string" then .
      elif type=="array" then ([.[] | .text? // empty] | join(" "))
      else empty end
    | gsub("\n"; " ") | .[0:200]
  ' 2>/dev/null | grep -v '^\s*<' | grep -v '^\s*$' | tail -5 | sed 's/^/· /'
}

# soc list — fzf 선택 → '--resume <UUID>' 클립보드 복사
soc_list() {
  _soc_require fzf jq
  local tsv out key sel uuid cwd
  tsv=$(mktemp)
  _soc_scan "${1:-50}" > "$tsv"
  if [ ! -s "$tsv" ]; then
    echo "세션을 찾지 못했습니다: $SOC_PROJECTS_DIR" >&2
    rm -f "$tsv"; return 1
  fi

  out=$(fzf < "$tsv" \
    --delimiter=$'\t' --with-nth=3,4,5 --ansi --no-sort \
    --expect=ctrl-y \
    --prompt='Socrates ❯ ' \
    --header=$'Enter: --resume UUID 복사 · Ctrl-Y: UUID만 복사 · ESC: 취소' \
    --preview="\"$SOC_ROOT/bin/soc\" __preview {1} {2}" \
    --preview-window=right,55%,wrap) || { rm -f "$tsv"; return 0; }
  rm -f "$tsv"

  key=$(printf '%s\n' "$out" | sed -n 1p)
  sel=$(printf '%s\n' "$out" | sed -n 2p)
  [ -n "$sel" ] || return 0
  uuid=$(printf '%s' "$sel" | cut -f1)
  cwd=$(printf '%s' "$sel" | cut -f6)

  if [ "$key" = "ctrl-y" ]; then
    printf '%s' "$uuid" | pbcopy
    echo "클립보드에 복사됨: $uuid"
  else
    printf -- '--resume %s' "$uuid" | pbcopy
    echo "클립보드에 복사됨: --resume $uuid"
    echo "프로젝트 폴더: $cwd"
    echo "예) claude --resume $uuid --dangerously-skip-permissions"
  fi
}

# soc name [별명] — 세션 선택 후 별명 부여/수정
soc_name() {
  _soc_require fzf jq
  local new_alias="${1:-}" tsv sel uuid cwd
  tsv=$(mktemp)
  _soc_scan 50 > "$tsv"
  if [ ! -s "$tsv" ]; then
    echo "세션을 찾지 못했습니다." >&2
    rm -f "$tsv"; return 1
  fi

  sel=$(fzf < "$tsv" \
    --delimiter=$'\t' --with-nth=3,4,5 --ansi --no-sort \
    --prompt='별명 붙일 세션 ❯ ' \
    --preview="\"$SOC_ROOT/bin/soc\" __preview {1} {2}" \
    --preview-window=right,55%,wrap) || { rm -f "$tsv"; return 0; }
  rm -f "$tsv"
  [ -n "$sel" ] || return 0
  uuid=$(printf '%s' "$sel" | cut -f1)
  cwd=$(printf '%s' "$sel" | cut -f6)

  if [ -z "$new_alias" ]; then
    printf '별명 입력: '
    read -r new_alias
    [ -n "$new_alias" ] || { echo "취소됨"; return 0; }
  fi
  new_alias=$(printf '%s' "$new_alias" | tr ' ' '-')

  bash "$SOC_ROOT/skills/socrates/socreg.sh" "$uuid" "$new_alias" "$cwd"
}
