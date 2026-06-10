# Socrates — "Know Your Self"

> γνῶθι σεαυτόν — Claude Code 세션·설정 관리 도구

[English](README.md) | **한국어**

여러 Claude Code CLI 세션을 운영할 때 (1) 리부팅 후 작업 중이던 세션 복귀, (2) `~/.claude/`와 프로젝트별 `.claude/`에 흩어진 설정(hooks, plugins, MCP, skills, agents) 현황 파악을 해결합니다.

> **플랫폼**: 현재 macOS 전용입니다 (`pbcopy`, `open`, BSD `stat` 사용). Linux/WSL 및 Windows 네이티브 지원은 로드맵에 있습니다.

## 설치

### 방법 A — 플러그인 (권장)

Claude Code 안에서:

```
/plugin marketplace add beret21/socrates
/plugin install socrates@beret21
```

`/socrates` 스킬이 등록되고, SessionStart 훅이 `socrates`/`soc` CLI를 `~/.local/bin`에 자동 연결합니다 (다음 세션 시작부터 일반 터미널에서도 사용 가능).

### 방법 B — 수동 설치

```bash
git clone https://github.com/beret21/socrates.git
cd socrates && ./install.sh        # 의존성: brew install fzf jq
```

`~/.zshrc`는 어느 방법이든 자동 수정하지 않습니다.

## 사용법

### Claude 세션 안에서 — 세션에 별명 붙이기

```
/socrates 내-작업-이름    # 현재 세션에 별명 등록
/socrates status         # 현재 세션 ID·별명 확인
```

### 터미널에서 — 정식 명령 `socrates`, 단축 별칭 `soc`

| 명령 | 동작 |
|------|------|
| `socrates` / `socrates list` | fzf 세션 목록. **Enter → `--resume <UUID>` 클립보드 복사**, Ctrl-Y → UUID만 복사 |
| `socrates name [별명]` | 세션을 선택해 별명 부여/수정 |
| `socrates map` | 설정 계층·hooks·plugins·MCP·skills/agents 현황을 터미널에 출력 |
| `socrates report` | HTML 대시보드(white 테마) 생성 후 브라우저로 열기 |
| `socrates doctor [--fix]` | 환경 점검: 의존성, PATH, 설치 링크, 레지스트리 무결성, 고아 alias, 버전. `--fix`는 끊어진/없는 CLI 링크 복구 |
| `socrates version` | 설치 버전 표시 + GitHub 최신 버전 확인 |

복사된 값은 옵션과 자유롭게 조합합니다:

```bash
claude --resume <UUID> --dangerously-skip-permissions
```

## 구조

```
.claude-plugin/        # plugin.json + marketplace.json (저장소 자체가 마켓플레이스)
bin/socrates           # CLI 진입점 (bin/soc 은 단축 심볼릭 링크)
hooks/hooks.json       # SessionStart: CLI를 ~/.local/bin 에 자동 연결
lib/soc-sessions.sh    # 세션 스캔 + fzf 선택기
lib/soc_report.py      # 설정 분석 + HTML 대시보드 (Python stdlib만)
skills/socrates/       # /socrates 슬래시 커맨드 + alias 레지스트리 스크립트
plan/                  # 설계 문서
```

데이터: `~/.claude/socrates/sessions.json` (alias 레지스트리), `~/.claude/socrates/report.html` (리포트)

## 안전 원칙

- `~/.claude/projects/`의 세션 jsonl은 **읽기 전용** — 절대 수정하지 않음
- 쓰기는 `~/.claude/socrates/` 아래에만
- `~/.zshrc` 자동 수정 없음

## 문제 해결 (Troubleshooting)

**`Plugin "socrates" not found in marketplace "beret21"`** — 이 기기에 마켓플레이스가 아직 등록되지 않은 것입니다. 설치는 항상 2단계입니다: `claude plugin marketplace add beret21/socrates` 먼저, 그다음 `claude plugin install socrates@beret21`.

**`brew install fzf`가 `no bottle available`로 실패** — macOS 프리릴리스(베타) 버전에서 발생합니다 (Homebrew가 Tier 2/3로 분류해 미리 빌드된 바이너리를 제공하지 않음). fzf 공식 설치 스크립트를 사용하세요 (컴파일 없이 prebuilt 바이너리 다운로드):

```bash
git clone --depth 1 https://github.com/junegunn/fzf.git ~/.fzf
~/.fzf/install --bin
ln -sfn ~/.fzf/bin/fzf ~/.local/bin/fzf
```

**플러그인 설치 직후 `socrates: command not found`** — CLI 링크는 SessionStart 훅이 만들기 때문에, Claude 세션을 한 번 시작하거나, Claude 없이 직접 생성할 수 있습니다:

```bash
bash ~/.claude/plugins/cache/beret21/socrates/*/bin/socrates doctor --fix
```

## 업데이트

기본은 수동 업데이트입니다. 각 명령은 하루 1회 GitHub의 최신 버전을 확인해, 새 버전이 있으면 실행 결과 끝에 한 줄 알림을 붙입니다. `socrates version`은 항상 실시간 확인합니다. 업데이트는 `/plugin update socrates@beret21`(플러그인) 또는 `git pull`(수동 설치)로 하고, 전후로 `socrates doctor`로 환경을 점검하세요.

## 버전 정책

`#.##` — 겸손하게, 1.0은 아주 멀리. 구조 변경은 소수점 첫째 자리, 사양 보완·체크 보강은 둘째 자리에서 판올림합니다.

## 환경 변수

- `SOC_EXCLUDE` — 목록에서 제외할 cwd 패턴 (grep -E, 기본값: claude-mem observer 세션 제외)

## License

[MIT](LICENSE)
