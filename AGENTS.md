# AGENTS.md

Make the smallest safe change that fully solves the problem.
기본 루프: **understand → scope → change → test → review → refactor if needed**.

## Rule Priority

규칙이 충돌하면 아래 우선순위를 따릅니다.

1. **Correctness**
2. **Security**
3. **Repository conventions**
4. **Clarity**
5. **Simplicity**

일반적인 스타일 규칙보다 저장소의 기존 아키텍처, 네이밍, 에러 처리, 테스트 패턴을 우선합니다. 단, 그것이 정확성, 보안, 유지보수성을 약화시키면 예외입니다.

## MUST

### Understand Before Changing

- 변경 전 짧은 problem brief를 남깁니다.
- problem brief에는 최소한 **Context**, **Problem**, **Goal**, **Non-Goals**, **Constraints**를 포함합니다.
- 다중 파일, 위험도가 높은 변경, 아키텍처 변경은 더 자세한 1-pager로 확장합니다.
- 수정 전에 1-3줄 impact note를 남깁니다.
- impact note에는 무엇이 바뀌는지, 무엇이 깨질 수 있는지, 어떤 테스트/문서를 함께 바꿔야 하는지를 포함합니다.
- 영향을 받는 파일은 수정 전에 처음부터 끝까지 읽습니다.
- 관련 정의, 참조, 호출 경로, 테스트, 설정, feature flag, 문서를 추적합니다.
- 심볼의 입력, 출력, 불변식, 부작용을 이해하기 전에는 수정하지 않습니다.

### Scope Control

- 작업, 커밋, PR은 작고 집중되게 유지합니다.
- 기능 변경과 무관한 리팩터링, rename, 의존성 업그레이드, formatting-only 변경을 섞지 않습니다.
- 변경 의도가 명시되지 않았다면 기존 공개 동작을 유지합니다.
- 동작, API, 스키마, 설정, UX가 바뀌면 diff, PR, ADR, 문서 중 적절한 위치에 명확히 남깁니다.

### Code Quality

- 의도가 드러나는 이름을 사용합니다.
- 숨은 마법보다 명시적인 코드를 선호합니다.
- 함수는 하나의 책임에 집중시킵니다.
- I/O, 네트워크, 파일시스템, 전역 상태 같은 부작용은 경계로 밀어냅니다.
- guard clause와 단순한 제어 흐름을 선호합니다.
- 하드코딩 값은 명확성을 높일 때만 상수로 치환합니다.
- 가능하면 **Input → Process → Return** 구조를 유지합니다.

### Errors, Logging, and Safety

- 예외는 구체적으로 잡습니다.
- 사용자에게는 실행 가능한 에러 메시지를 제공합니다.
- 코드베이스가 지원하면 structured logging을 사용합니다.
- 시크릿이나 민감한 데이터는 로그에 남기지 않습니다.
- 입력은 적절히 검증, 정규화, 인코딩합니다.
- 데이터베이스나 query-like 작업은 parameterized operation을 사용합니다.
- 권한, 자격 증명, 접근 범위는 least privilege를 적용합니다.

### Testing

- 새 코드는 테스트를 동반해야 합니다.
- 버그 수정에는 회귀 테스트가 필요하며, 가능하면 먼저 실패하도록 작성합니다.
- 테스트는 결정적이고 서로 독립적이어야 합니다.
- 외부 시스템은 fake, mock, contract test로 대체합니다.
- 동작이 바뀌면 테스트와 관련 문서를 같은 변경에 포함합니다.
- 기능 추가/버그 수정은 기본적으로 Red/Green/Refactor 사이클을 따릅니다.
- Red: 먼저 실패하는 테스트를 작성하고 실패를 확인한 뒤 구현을 시작합니다.
- Green: 테스트를 통과시키는 최소한의 코드만 작성합니다.
- Refactor: 테스트가 통과한 상태에서만 중복 제거와 구조 개선을 수행합니다.
- 버그 수정 시 재현 테스트 없이 코드부터 수정하지 않습니다.
- 사이클 완료 전 품질 게이트를 모두 통과합니다.
- 권장: `just quality`
- fallback: `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`, `UV_CACHE_DIR=.uv-cache uv run ruff check .`, `UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml`

## SHOULD

### Decision-Making

- 비사소한 변경은 최소 두 가지 이상 실행 가능한 옵션을 비교합니다.
- 각 옵션에 대해 **pros**, **cons**, **risks**를 한 줄씩 남깁니다.
- 목표를 안전하게 만족하는 가장 단순한 해법을 선택합니다.

### Design and Maintainability

- 작은 파일, 작은 함수를 선호합니다.
- 이른 추상화는 피합니다.
- DRY는 적용하되, 중복이 실제로 반복되고 안정적일 때만 추상화합니다.
- 인터페이스는 단순하고 명시적으로 유지합니다.
- 숨은 결합보다 composition을 선호합니다.

### Size Targets

아래는 기본 목표이며 절대적인 차단 기준은 아닙니다.

- file: **~300 LOC or less**
- function: **~50 LOC or less**
- parameters: **~5 or fewer**
- cyclomatic complexity: **~10 or lower**

이 기준을 넘는 편이 더 명확하거나 저장소 관례에 맞다면 그대로 두고 짧은 이유를 남깁니다.

### Review Mindset

- 시니어 엔지니어의 관점으로 검토합니다.
- 추측에 기대어 행동하지 않습니다.
- "동작한다"에서 멈추지 말고, 이해 가능성, 테스트 가능성, 안전성을 확인합니다.
- 리팩터링은 위험을 줄이거나 수정한 범위의 명확성을 의미 있게 높일 때만 수행합니다.

## WHEN APPLICABLE

### Time

- 시간대, DST, locale, 날짜 경계, 장 시작/종료 같은 clock boundary를 고려합니다.

### Concurrency / Reliability

- 동시성, 잠금, 재시도, 멱등성, 중복 실행, race condition, deadlock 위험을 검토합니다.

### Distributed Systems / Observability

- 시스템이 지원하면 request ID, trace ID, correlation ID를 전파합니다.
- 유용한 metrics, logs, tracing hook을 보존합니다.

### End-to-End Tests

- 가능하면 happy path와 failure path를 최소 하나씩 포함합니다.

### Security-Sensitive Paths

- auth, authz, secret handling, token flow, redirect, deserialization, file access, external input boundary를 특히 주의해서 검토합니다.

## ANTI-PATTERNS

- 관련 맥락을 충분히 읽지 않고 코드를 바꾸지 않습니다.
- 추측성 변경을 하지 않습니다.
- 코드, 로그, 테스트, 티켓, 스크린샷에 시크릿을 노출하지 않습니다.
- 경고, 실패 테스트, flaky 동작을 무시하지 않습니다.
- 문서화된 이유 없이 broad exception을 쓰지 않습니다.
- 정당한 이유 없는 추상화, 간접화, 최적화를 도입하지 않습니다.
- 동작, 계약, 기본값을 조용히 바꾸지 않습니다.
- 정확성, 보안, 데이터 무결성 관련 핵심 TODO를 남기지 않습니다.

## CHANGE CHECKLIST

- 문제를 명확히 정의했습니다.
- 변경이 가장 작은 안전한 해법입니다.
- 영향을 받는 파일을 모두 끝까지 읽었습니다.
- 관련 참조와 호출 경로를 확인했습니다.
- 가정을 기록했습니다.
- 테스트가 변경을 커버합니다.
- 필요한 문서, 설정, 메시지를 함께 업데이트했습니다.
- 시크릿이 추가되지 않았습니다.
- diff가 집중되어 있고 리뷰 가능 상태입니다.

## 저장소 전용 규칙

### 실행 우선순위

- 도구체인 동기화: `mise install`
- 도구 버전 변경 시 lock 갱신: `mise lock --platform linux-x64,macos-arm64 && mise install`
- direnv zsh 훅(1회): `echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc`
- direnv 프로젝트 허용(최초 1회): `direnv allow .`
- direnv는 `.env`를 자동 로드하지 않습니다(`.envrc.local`만 로드).
- 시크릿/개인 오버라이드는 `.envrc.local`에만 저장하고 커밋하지 않습니다.

### 권장 명령 (just)

- 레시피 목록: `just --list`
- 의존성/락: `just sync`, `just lock-upgrade`
- 트레이딩 실행: `just scan`, `just sell`, `just entry`
- 품질 게이트: `just quality` (`just check`는 동일 동작 alias)
- pre-commit: `just precommit-all`
- CI 대응 실행: `just ci-python`, `just ci-web` (`ci-web`는 비밀 없는 고정 CI placeholder env로만 실행)

### 직접 실행 (uv fallback)

- `UV_CACHE_DIR=.uv-cache uv sync --all-extras --dev`
- `UV_CACHE_DIR=.uv-cache uv lock --upgrade`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab scan`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab sell`
- `UV_CACHE_DIR=.uv-cache uv run ruff check .`
- `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
- `UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml`
- `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`

### 문서(설계 로직)

- 설계 로직(신호/리스크/평가 기준/모드별 규칙)이 변경될 경우 [STRATEGY.md](docs/STRATEGY.md)를 함께 업데이트합니다.
- 로직/플로우/컴포넌트 책임이 변경될 경우 [ARCHITECTURE.md](docs/ARCHITECTURE.md) 업데이트 필요 여부를 함께 검토합니다.

### Pre-commit (샌드박스)

- 권장: `just precommit-all`
- 단일 훅 실행(권장): `just precommit mypy --all-files`
- 설정 검사(권장): `just precommit-validate`
- 전체 실행: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run --all-files`
- 단일 훅 실행: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run mypy --all-files`
- 훅 업데이트: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit autoupdate`
- 설정 검사: `UV_CACHE_DIR=.uv-cache uv run pre-commit validate-config`
- 첫 실행 시 훅 저장소를 내려받기 위해 네트워크 접근이 필요할 수 있습니다.
- 커밋 시 staged 파일에 `web/` 변경이 있으면 `pnpm --dir web run lint`와 `pnpm --dir web run format:check`를 검사합니다.
- `web` 타입체크는 pre-commit에서 제외하고 CI(`.github/workflows/ci.yml`의 web job)에서 `pnpm run typecheck`로 강제합니다.

### 웹 스모크 체크

- 우선순위: 샌드박스에서 `next dev` 포트 바인딩이 `EPERM`으로 막힐 수 있으므로, `sab-web` 컨테이너가 실행 중이면 `http://127.0.0.1:${WEB_HOST_PORT}`로 먼저 검증합니다.
- `/run` 성공 조건: `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_PAT`가 비어 있으면 `/api/run`이 500(Zod validation)으로 실패합니다.
- 브라우저 자동화 폴백: Playwright Chrome 런치가 세션 충돌로 실패할 수 있으므로, 이런 경우 `chrome-devtools` 기반 체크로 전환합니다.

### GitHub Actions 린트 팁

- `workflow_audit`의 `actionlint`는 `shellcheck` 스타일 경고(`SC2129`)도 실패로 처리될 수 있습니다.
- GitHub Actions `run: |`에서 heredoc(`cat <<'EOF'`) 사용 시 종료 토큰(`EOF`)은 줄 맨 앞(무들여쓰기)이어야 합니다. 들여쓰기가 들어가면 `SC1039`, `SC1072`, `SC1073`로 실패할 수 있습니다.
- 단순 문자열 파일 생성은 heredoc 대신 `printf`를 우선 사용합니다.
- 워크플로 문법/쉘 린트는 로컬에서 다음 명령으로 재현합니다: `docker run --rm -v "$PWD":/work -w /work rhysd/actionlint:latest`
- 로컬에서 `python` 실행이 불안정할 수 있으므로, 저장소 작업 스크립트는 `uv run python ...`을 우선 사용합니다.

### Context7 MCP

- 라이브러리/API 문서, 코드 생성, 설정/구성 단계가 필요할 때 사용자가 명시적으로 요청하지 않아도 항상 Context7 MCP를 사용합니다.
- `resolve-library-id`로 라이브러리 ID를 먼저 조회한 뒤 `query-docs`로 최신 문서를 가져옵니다.

### 커밋

- Conventional Commits 형식을 사용합니다.
- 의미 단위로 커밋합니다.
- 하나의 커밋에는 하나의 의도만 담습니다.
- 서로 다른 관심사가 섞여 있으면 커밋을 분리합니다.
- 모호한 커밋 메시지는 피합니다.
- 커밋 메시지의 제목과 본문은 한글로 작성합니다.
- 커밋 메시지 기본 형식은 제목 1줄(`type(scope): 요약`) + 빈 줄 1줄 + 본문(필요한 경우)입니다.
- 본문은 문장마다 줄을 띄우지 않고 문단 단위로 작성합니다.
- CLI에서 `-m`를 문장별로 여러 번 쓰지 않습니다.
- 권장 형식: `git commit -m "제목" -m "본문 전체"`
- 본문 줄바꿈이 필요하면 `"\n"`을 더블쿼트 안에 넣지 않습니다(문자 그대로 `\n`이 저장될 수 있음).
- 줄바꿈 권장 방식: zsh의 `$'...'` 인용 사용. 예: `git commit -m "chore(ci): ..." -m $'- 항목1\n- 항목2'`
- 줄바꿈 대안: `git commit`으로 편집기를 열어 작성합니다.
- 이미 푸시한 커밋 메시지를 고칠 때는 `git rebase -i`로 `reword` 후 `git push --force-with-lease`를 사용합니다(브랜치 정책/협업 상황 확인).
- `git status`, `git add`, `git commit` 같은 git 명령은 `/bin/zsh -lc` 같은 셸 래퍼 없이 직접 실행합니다.
- `git push`는 권한 상승(`sandbox_permissions="require_escalated"`)으로 실행합니다.
