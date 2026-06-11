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
/socrates:name 내-작업-이름    # 현재 세션에 고유 별명 등록
/socrates:status              # 현재 세션 ID·별명 확인
```

별명은 **세션 간 중복 불가**입니다 — 이 도구의 목적이 동시 세션 구분이기 때문입니다 (예: 같은 폴더에서 `제안서-본문`, `제안서-hwpx`, `제안서-이미지`). 다른 세션이 쓰는 이름은 등록이 거부됩니다. 오타라면 다시 등록하면 덮어쓰며(이전 별명 표시), `socrates unname`으로 이름을 해제할 수 있습니다.

(수동 설치 시 커맨드는 `/socrates-name`, `/socrates-status`입니다.)

### 터미널에서 — 정식 명령 `socrates`, 단축 별칭 `soc`

| 명령 | 동작 |
|------|------|
| `socrates` / `socrates list` | fzf 세션 목록. **Enter → 액션 메뉴** (`--resume` 복사 / `cd … && claude --resume …` 전체 복사 / UUID만 / 별명 / 뒤로); 단축키: **Ctrl-P 선택 세션의 프로젝트로 좁히기**, Ctrl-O cd+resume, Ctrl-Y UUID, Ctrl-N 별명. Shift-↑↓ preview 스크롤, Ctrl-/ preview 확대 |
| `socrates projects` | 프로젝트별 2단계 탐색 (저장 폴더가 곧 그룹 키 — 세션 수·★별명·최근 활동 요약이 즉시 표시); Enter로 그 프로젝트의 세션 목록, ESC로 뒤로 |
| `socrates find <텍스트>` | **이 기기 모든 세션의 대화 내용 전문 검색** — 네이티브 picker가 못 하는 기능. 매치 세션이 같은 picker로 열리고 preview에 매치 문맥이 하이라이트됨 |
| `socrates name [별명]` | 세션을 선택해 별명 부여/수정 |
| `socrates unname` | 별명을 선택해 제거 (세션 자체는 그대로) |
| `socrates map` | 설정 계층·hooks·plugins·MCP·skills/agents 현황을 터미널에 출력 |
| `socrates report` | 탭형 HTML 대시보드 생성+열기 (Overview / Projects / Sessions / **Config X-ray** / Harness). X-ray는 프로젝트별로 설정 레이어와 **CLAUDE.md 체인** — 루트→프로젝트로 내려오며 세션 시작 시 실제 로드되는 모든 메모리 파일([공식 규칙](https://code.claude.com/docs/en/memory#how-claude-md-files-load)) — 을 크기·조상 폴더 경고와 함께 표시 |
| `socrates update` | 터미널 한 줄 업데이트: 플러그인(스킬+CLI) 갱신 + 링크 즉시 전환 — claude 실행 불필요. 수동 설치는 `git pull` 수행 |
| `socrates doctor [--fix]` | 환경 점검: 의존성, PATH, 설치 링크, 레지스트리 무결성, 고아 alias, 버전. `--fix`는 끊어진/없는 CLI 링크 복구 |
| `socrates version` | 설치 버전 표시 + GitHub 최신 버전 확인 |

**주의:** `claude --resume`은 해당 세션의 프로젝트 폴더에서만 세션을 찾습니다 — `cd` 후 실행하세요 (picker가 정확한 명령을 출력하고, Ctrl-O는 전체를 복사합니다):

```bash
cd "/path/to/that/project" && claude --resume <UUID> --dangerously-skip-permissions
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

## Claude Code 네이티브 기능과의 관계

Claude Code 자체에도 세션 도구가 있습니다 — Socrates는 경쟁하지 않고 통합합니다:

- **네이티브 세션 이름**(`claude -n`, `/rename`)을 picker가 읽어 표시합니다. 이름 우선순위: ★ Socrates 별명 → 네이티브 이름 → 자동 slug → 첫 메시지.
- **찾아서 바로 들어가기**는 네이티브 `claude --resume` picker가 이미 잘합니다 (이름/첫 프롬프트 검색, `Ctrl+A` 전체 프로젝트). 바로 진입할 때는 그것을 쓰세요.
- **Socrates는 네이티브에 없는 것을 더합니다**: 대화 내용 전문 검색(`find`), 기본값이 전 프로젝트 범위, 실행 대신 복사(플래그 직접 조합), 세션을 열지 않고 사후 명명, 설정·하네스 map과 HTML report, `doctor`.

### Desktop ↔ CLI 세션 이동 (실측 검증)

기록은 한 저장소(`~/.claude/projects/`)를 공유하므로 세션은 프런트엔드를 넘나듭니다 — 단, 제목과 사이드바 목록은 프런트엔드별 관리입니다:

| 방향 | 방법 | 전달 범위 |
|------|------|----------|
| Desktop → CLI | `socrates list`/`find` → 복사 → `cd "<프로젝트>" && claude --resume <UUID>` | 대화 전체 ✓ |
| CLI → Desktop | CLI 세션 안에서 **메시지를 최소 1개 보낸 뒤** `/desktop` | 대화 전체 ✓ — 단 네이티브 이름(customTitle)은 Desktop 제목에 표시되지 않음 |
| CLI 세션의 Desktop 사이드바 자동 표시 (핸드오프 없이) | 미지원 — Desktop과 CLI는 세션 목록을 따로 관리 | `/desktop`으로 핸드오프 |

## 문제 해결 (Troubleshooting)

**`Plugin "socrates" not found in marketplace "beret21"`** — 이 기기에 마켓플레이스가 아직 등록되지 않은 것입니다. 설치는 항상 2단계입니다: `claude plugin marketplace add beret21/socrates` 먼저, 그다음 `claude plugin install socrates@beret21`.

**`Plugin "socrates/beret21" not found`** — 구분자 혼동입니다. `/`는 `marketplace add beret21/socrates`의 GitHub 좌표(소유자/저장소)에만 쓰이고, install/update/uninstall은 모두 `@`를 씁니다: `socrates@beret21` (플러그인@마켓플레이스). 요령: **바깥(GitHub)은 `/`, 안(등록된 카탈로그)은 `@`**.

**`brew install fzf`가 `no bottle available`로 실패** — macOS 프리릴리스(베타) 버전에서 발생합니다 (Homebrew가 Tier 2/3로 분류해 미리 빌드된 바이너리를 제공하지 않음). fzf 공식 설치 스크립트를 사용하세요 (컴파일 없이 prebuilt 바이너리 다운로드):

```bash
git clone --depth 1 https://github.com/junegunn/fzf.git ~/.fzf
~/.fzf/install --bin
ln -sfn ~/.fzf/bin/fzf ~/.local/bin/fzf
```

**`claude -n <이름>`이 아무 효과가 없거나 `/desktop`이 "transcript not found"를 낼 때** — Claude Code는 세션의 **첫 실제 메시지** 이후에야 transcript 파일을 만듭니다. 아무 말 없이 종료하거나 메시지 전에 `/desktop`을 치면 기록 자체가 없어 이름 붙일 대상도, Desktop이 열 대상도 없습니다. 메시지를 하나 보낸 뒤 시도하세요.

**플러그인 설치 직후 `socrates: command not found`** — CLI 링크는 SessionStart 훅이 만들기 때문에, Claude 세션을 한 번 시작하거나, Claude 없이 직접 생성할 수 있습니다:

```bash
bash ~/.claude/plugins/cache/beret21/socrates/*/bin/socrates doctor --fix
```

## 업데이트

기본은 수동 업데이트입니다. 각 명령은 하루 1회 GitHub의 최신 버전을 확인해, 새 버전이 있으면 실행 결과 끝에 한 줄 알림을 붙입니다. `socrates version`은 항상 실시간 확인합니다. **`socrates update` 하나로 전부 처리됩니다** — 플러그인 갱신 + CLI 링크 즉시 전환, claude 실행 불필요 (수동 설치는 `git pull`). 버전 건너뛰기(예: 0.11 → 0.13)는 안전합니다 — 매 릴리스가 완전한 복사본이며 마이그레이션 단계가 없습니다. 업데이트 전후로 `socrates doctor`로 환경을 점검하세요.

## 버전 정책

`#.##` — 겸손하게, 1.0은 아주 멀리. 구조 변경은 소수점 첫째 자리, 사양 보완·체크 보강은 둘째 자리에서 판올림합니다.

## 환경 변수

- `SOC_EXCLUDE` — 목록에서 제외할 cwd 패턴 (grep -E, 기본값: claude-mem observer 세션 제외)

## License

[MIT](LICENSE)
