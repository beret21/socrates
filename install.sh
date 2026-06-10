#!/bin/bash
# Socrates 설치 스크립트
#  1. ~/.local/bin/socrates (+ 단축 별칭 soc) → bin/socrates 심볼릭 링크
#  2. ~/.claude/skills/socrates → skills/socrates 심볼릭 링크 (/socrates 슬래시 커맨드)
#  3. zsh 래퍼 스니펫 안내 (~/.zshrc 는 자동 수정하지 않음)
# 플러그인으로 설치하는 경우 이 스크립트는 필요 없습니다 (README 참고).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Socrates 설치 — $ROOT"
echo ""

# 의존성 확인
missing=""
for dep in fzf jq python3; do
  command -v "$dep" >/dev/null 2>&1 || missing="$missing $dep"
done
if [ -n "$missing" ]; then
  echo "필요한 도구가 없습니다:$missing"
  echo "설치: brew install$missing"
  exit 1
fi

# 1. socrates 명령어 (+ 단축 별칭 soc)
mkdir -p "$HOME/.local/bin"
ln -sfn "$ROOT/bin/socrates" "$HOME/.local/bin/socrates"
ln -sfn "$ROOT/bin/socrates" "$HOME/.local/bin/soc"
chmod +x "$ROOT/bin/socrates" "$ROOT/skills/socrates/socreg.sh"
echo "✓ $HOME/.local/bin/socrates → $ROOT/bin/socrates (단축 별칭 soc 포함)"

# 2. /socrates 스킬
mkdir -p "$HOME/.claude/skills"
ln -sfn "$ROOT/skills/socrates" "$HOME/.claude/skills/socrates"
echo "✓ ~/.claude/skills/socrates → $ROOT/skills/socrates  (/socrates 슬래시 커맨드)"

# 구버전(/soc 스킬) 링크가 이 저장소를 가리키면 정리
if [ -L "$HOME/.claude/skills/soc" ] && [[ "$(readlink "$HOME/.claude/skills/soc")" == "$ROOT"* ]]; then
  rm "$HOME/.claude/skills/soc"
  echo "✓ 구버전 스킬 링크(~/.claude/skills/soc) 정리"
fi

# 3. PATH / 래퍼 안내
echo ""
case ":$PATH:" in
  *":$HOME/.local/bin:"*) echo "✓ ~/.local/bin 이 PATH에 있습니다." ;;
  *)
    echo "⚠ ~/.local/bin 이 PATH에 없습니다. ~/.zshrc 에 추가하세요:"
    echo '    export PATH="$HOME/.local/bin:$PATH"'
    ;;
esac

cat <<'EOF'

선택: 'claude soc list' 형태도 쓰려면 ~/.zshrc 에 아래 래퍼를 추가하세요
(자동으로 수정하지 않습니다):

  claude() {
    if [[ "$1" == "soc" ]]; then shift; soc "$@"; else command claude "$@"; fi
  }

설치 완료. 사용법: socrates help  (단축: soc help)
EOF
