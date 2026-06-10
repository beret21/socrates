# Socrates — "Know Your Self"

> Claude Code 세션·설정 관리 도구
> γνῶθι σεαυτόν — 너 자신을 알라. 당신의 Claude 환경을 알라.

작성일: 2026-06-10

---

## 1. 문제 정의

여러 Claude Code CLI 세션을 동시에 운영하는 환경에서 두 가지 문제가 있다.

| # | 문제 | 현재 상태 |
|---|------|----------|
| 1 | **세션 복귀의 어려움** — 맥 리부팅(OS 업데이트 등) 후 작업 중이던 세션을 다시 찾기 어렵다 | `claude --resume <UUID>`로 복귀는 가능하지만 UUID를 기억/관리할 방법이 없다 |
| 2 | **설정 현황 파악의 어려움** — `~/.claude/`와 프로젝트별 `.claude/`에 흩어진 설정, 하네스 엔지니어링으로 늘어난 서브에이전트/스킬 현황을 한눈에 볼 수 없다 | 폴더를 일일이 열어봐야 함 |

## 2. 해결 방향 (합의 완료)

| 영역 | 결정 |
|------|------|
| 세션 안 | `/soc` 슬래시 커맨드로 현재 세션에 alias 부여 |
| 터미널 | `soc` 독립 명령 + `claude soc ...` zsh 래퍼 |
| 세션 선택 | fzf TUI에서 선택 → **`--resume <UUID>` 문자열이 클립보드로 복사** (자동 실행 안 함 — `--dangerously-skip-permissions` 등 옵션을 직접 조합하기 위함) |
| 현황 보기 | 터미널 요약 `soc map` + 정적 HTML 대시보드 `soc report` |
| 구현 스택 | 선택기: shell + fzf + jq / 분석·HTML: Python 표준 라이브러리 |

## 3. 기반 사실 (공식 문서 + 로컬 검증, 2026-06-10)

- **세션 저장 위치**: `~/.claude/projects/<경로의 '/'를 '-'로 인코딩>/<세션UUID>.jsonl`
  - 각 라인에 `sessionId`, `cwd`, `timestamp`, `gitBranch`, `slug`(자동 생성 별명), `version` 포함
- **세션 ID 획득**: SKILL.md 안에서 `${CLAUDE_SESSION_ID}` 치환 공식 지원 — [docs/skills](https://code.claude.com/docs/en/skills)
- **스킬 위치**: `~/.claude/skills/<name>/SKILL.md` (개인 전역) — [docs/skills](https://code.claude.com/docs/en/skills)
- **재개**: `claude --resume "<id>"` / `claude -r` — [docs/cli-reference](https://code.claude.com/docs/en/cli-reference)
- **프로젝트 메타데이터**: `~/.claude.json`의 `projects` 키 — `lastSessionId`, 비용, 모델 사용량
- **이름 충돌 없음**: `~/.claude/skills/`, `~/.claude/commands/`에 사용자 커맨드 없음 → `/soc`, `soc` 사용 가능
- **주의**: `claude --soc` 같은 커스텀 플래그는 공식 미지원 → zsh 래퍼 함수로 `claude soc ...`를 라우팅

## 4. 아키텍처

```
┌─ Claude 세션 안 ────────────────────┐    ┌─ 터미널 ──────────────────────────┐
│  /soc <별명>                         │    │  soc list   (fzf 선택기)          │
│  └─ ${CLAUDE_SESSION_ID} + cwd 기록 │    │  soc name   (alias 부여/수정)     │
│                                      │    │  soc map    (설정 현황, 터미널)   │
│                                      │    │  soc report (HTML 대시보드)      │
└──────────────┬───────────────────────┘    └──────┬────────────────────────────┘
               │ 쓰기                              │ 읽기/쓰기
               ▼                                   ▼
        ~/.claude/socrates/sessions.json  ← alias 레지스트리 (유일한 쓰기 대상)
               ▲                                   │ 읽기 전용
               │                                   ▼
        ~/.claude/projects/*/*.jsonl   ~/.claude/settings.json   ~/.claude.json
        (세션 기록)                     (+ 계층별 .claude/)       (프로젝트 메타)
```

### 파일 구조

```
Socrates/
├── plan/PLAN.md, PLAN.html    # 이 설계 문서
├── bin/soc                    # 메인 진입점 (서브커맨드 라우팅)
├── lib/soc-sessions.sh        # 세션 스캔 + fzf 선택기
├── lib/soc_report.py          # 설정 분석 + 터미널 요약 + HTML 생성
├── skills/soc/SKILL.md        # /soc 슬래시 커맨드
├── install.sh                 # 설치 (심볼릭 링크 + 래퍼 안내)
└── README.md
```

### 데이터: `~/.claude/socrates/sessions.json`

```json
{
  "123e4567-e89b-12d3-a456-426614174000": {
    "alias": "socrates-bootstrap",
    "cwd": "~/Projects/Socrates",
    "named_at": "2026-06-10T08:30:00+09:00"
  }
}
```

## 5. 명령어 사양

### `/soc` (Claude 세션 안)

| 사용법 | 동작 |
|--------|------|
| `/soc <별명>` 또는 `/soc name <별명>` | 현재 세션 UUID에 alias 기록 |
| `/soc` 또는 `/soc status` | 현재 세션 ID·alias·프로젝트, 등록 세션 수 표시 |

- `disable-model-invocation: true` — 사용자 명시 호출 전용
- 최소 권한: `Bash(jq:*)`, `Bash(mkdir:*)` 수준

### `soc` (터미널)

| 명령 | 동작 |
|------|------|
| `soc` / `soc list` | fzf 목록: alias 세션(★ 상단) + 최근 세션 ~50개. **Enter → `--resume <UUID>` 클립보드 복사**, Ctrl-Y → UUID만 복사 |
| `soc name [별명]` | fzf로 세션 선택 후 alias 부여/수정 |
| `soc map` | 설정 계층(전역→Codes→Projects→프로젝트), hooks, plugins, MCP, skills/agents를 ANSI 트리로 출력 |
| `soc report` | `~/.claude/socrates/report.html` 생성 후 브라우저로 열기 |

fzf preview 창: 전체 경로, gitBranch, 마지막 사용자 메시지.

### HTML 리포트 섹션

1. 프로젝트 × 세션 테이블 (alias 강조, `--resume UUID` 복사 버튼)
2. 설정 계층 트리 (전역 → 부모 폴더 → 프로젝트)
3. 하네스 인벤토리: 에이전트 / 스킬 / 플러그인 / MCP 서버
4. 비용·모델 사용량 요약 (`~/.claude.json` 기반)

## 6. 안전 원칙

- `~/.claude/projects/` 내 jsonl은 **읽기 전용** — 쓰기는 오직 `~/.claude/socrates/` 아래에만
- `~/.zshrc` 자동 수정 금지 — 래퍼 스니펫 안내만
- 대용량 jsonl 대비 `tail` 기반 마지막 라인 파싱
- macOS 전용 (pbcopy, open). 의존성: fzf, jq

## 7. 검증 계획

| 단계 | 검증 방법 |
|------|----------|
| /soc 스킬 | `/soc name test` 후 `sessions.json` 기록 확인 |
| soc list | 선택 → `pbpaste` == `--resume <uuid>` → `claude --resume`로 실제 재개 |
| soc map/report | 출력이 실제 설정(41개 프로젝트 폴더, 활성 플러그인)과 일치 |
| 래퍼 | `claude soc list` == `soc list`, `command claude --version` 정상 |

---

## 결정 변경 이력

### 2026-06-10 (구현 후 합의)

1. **이름 통일**: 정식 이름은 `socrates` 하나로 통일. 슬래시 커맨드 `/socrates`(자동완성으로 풀네임 부담 없음, 고유명사라 미래 내장 명령과 충돌 위험 최소), 터미널 정식 `socrates` + 단축 별칭 `soc`. 스킬 폴더 `skills/soc` → `skills/socrates`.
2. **배포 방식**: 플러그인 구조 추가 (`.claude-plugin/plugin.json` + `marketplace.json` + `hooks/hooks.json`). 저장소 자체가 마켓플레이스 — `/plugin marketplace add beret21/socrates` → `/plugin install socrates@beret21`. SessionStart 훅이 CLI를 `~/.local/bin`에 자동 연결하므로 설치 이원화 불필요. 수동 설치(`install.sh`)는 보조 경로로 유지.
3. **HTML white 배경**: 모든 HTML 산출물은 라이트 테마 (다크 버전은 `History/PLAN_2026-06-10_v1.html`에 보존).
