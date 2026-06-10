---
name: socrates
description: Socrates — 현재 Claude 세션에 alias(별명)를 등록하거나 세션 등록 상태를 확인한다. 등록된 세션은 터미널에서 `socrates list`(단축 `soc list`)로 찾아 재개할 수 있다.
argument-hint: "[별명] | name <별명> | status"
disable-model-invocation: true
allowed-tools: Bash(bash:*), Bash(jq:*)
---

# Socrates 세션 alias 관리

현재 세션 ID: `${CLAUDE_SESSION_ID}`
전달된 인자: `$ARGUMENTS`

레지스트리 스크립트: `${CLAUDE_SKILL_DIR}/socreg.sh` (쓰기 대상은 `~/.claude/socrates/sessions.json` 뿐)

## 동작 규칙

인자를 해석해 아래 중 하나를 수행하라. 다른 파일은 절대 수정하지 않는다.

주의: `status`, `help`, `도움말`은 예약어다 — 절대 별명으로 등록하지 마라.

### 1. 인자가 없거나 `status`인 경우 — 상태 조회

```bash
bash "${CLAUDE_SKILL_DIR}/socreg.sh" "${CLAUDE_SESSION_ID}"
```

출력 결과를 바탕으로 현재 세션의 ID, 별명(없으면 없다고), 현재 프로젝트 폴더, 전체 등록 세션 수를 한국어로 간결히 보고하라.

### 2. 인자가 `help` 또는 `도움말`인 경우 — 사용법 안내 (별명으로 등록 금지)

스크립트를 실행하지 말고 아래 사용법을 한국어로 안내하라:
- `/socrates <별명>` — 현재 세션에 별명 등록
- `/socrates status` — 현재 세션 ID·별명 확인
- 터미널: `socrates list`(단축 `soc`) — 세션 선택 → `--resume <UUID>` 클립보드 복사, `socrates map`/`report` — 설정 현황

### 3. 그 외 — 별명 등록

- 인자가 `name <별명>` 형태면 `name` 뒤의 텍스트만 별명으로 사용한다.
- 그 외에는 인자 전체를 별명으로 사용한다.
- 별명에 공백이 있으면 하이픈(`-`)으로 치환한다.

```bash
bash "${CLAUDE_SKILL_DIR}/socreg.sh" "${CLAUDE_SESSION_ID}" "<별명>" "$PWD"
```

stderr에 "이미 다른 세션에 사용 중" 경고가 나오면 사용자에게 알리되, 등록 자체는 완료된 것이다 (덮어쓰기 허용 정책).

성공 시 사용자에게 보고할 것:
- 등록된 별명과 세션 ID
- 터미널에서 `socrates list`(단축 `soc list`)로 이 세션을 찾을 수 있고, Enter를 누르면 `--resume <UUID>`가 클립보드로 복사된다는 안내
