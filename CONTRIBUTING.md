# 기여 가이드 (Contributing Guide)

이 문서는 이 저장소에 기여할 때 따라야 할 기준을 정리합니다.  
This document defines how to contribute to this repository safely and consistently.

참고: `AGENTS.md`는 사람 기여자용이 아닌 에이전트 작업 지침입니다.  
Note: `AGENTS.md` is an agent-only operational guide, not a contributor-facing standard.

## 1) 기여 가이드 개요 (Contribution Guide Overview)

이 프로젝트는 기본적으로 1인 운영(maintainer 중심)입니다.  
This project is primarily maintained by a single maintainer.

- 기여 유형: 코드 개선, 문서 보완, 버그 리포트, 운영 개선 제안
- 작은 변경은 바로 제안해도 좋고, 큰 변경(아키텍처/동작 변경)은 먼저 이슈로 합의합니다.
- 저장소 운영 기본은 `main` 직접 반영이며, 필요 시 feature branch/PR을 사용합니다.
- 외부 기여자는 이슈로 방향을 먼저 맞춘 뒤 branch + PR 흐름을 권장합니다.

## 2) 개발 환경 준비 (Local Setup)

로컬에서 동일한 검증 결과를 재현하려면 아래 환경을 맞춰 주세요.  
Use the same toolchain below to reproduce local and CI behavior.

- Python 3.14+
- `uv`
- (웹 변경 시) Node.js + `pnpm`

표준 의존성 동기화 명령:

```bash
UV_CACHE_DIR=.uv-cache uv sync --all-groups
```

잠금 파일 정합성만 갱신할 때(권장 기본):

```bash
UV_CACHE_DIR=.uv-cache uv lock
```

전체 optional dependency까지 모두 포함해야 할 때:

```bash
UV_CACHE_DIR=.uv-cache uv sync --all-extras --all-groups
```

의존성 버전 상향이 목적일 때만:

```bash
UV_CACHE_DIR=.uv-cache uv lock --upgrade
```

## 3) 로컬 검증 (Local Quality Checks)

커밋 전에 아래 검증을 순서대로 실행하는 것을 권장합니다.  
Run these checks before committing to avoid CI-only failures.

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check .
UV_CACHE_DIR=.uv-cache uv run ruff format --check .
UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q
```

실행 스모크 예시:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m sab scan
UV_CACHE_DIR=.uv-cache uv run python -m sab sell
```

참고: `scan`/`sell`은 환경변수/외부 연동 상태에 따라 실행 성공 여부가 달라질 수 있습니다.  
Note: `scan`/`sell` may require valid runtime secrets and external connectivity.

## 4) pre-commit 사용법 (Pre-commit in Sandbox)

pre-commit은 로컬 품질 게이트를 빠르게 재현하는 기본 도구입니다.  
Use pre-commit to run the same baseline checks quickly in local environments.

전체 훅 실행:

```bash
PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run --all-files
```

단일 훅 실행(예: mypy):

```bash
PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run mypy --all-files
```

훅 업데이트:

```bash
PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit autoupdate
```

설정 검사:

```bash
UV_CACHE_DIR=.uv-cache uv run pre-commit validate-config
```

- 첫 실행 시 훅 저장소 다운로드를 위해 네트워크 접근이 필요할 수 있습니다.
- staged 파일에 `web/` 변경이 있으면 `pnpm --dir web run lint`, `pnpm --dir web run format:check`가 실행됩니다. staged 변경이 `web/src/app/`를 포함하면 `web-route-static-check` 훅(`uv run python scripts/check_next_app_routes.py`)도 실행됩니다.
- `web` 타입체크는 pre-commit에서 제외되며 CI(`.github/workflows/ci.yml`)의 web job에서 `pnpm run typecheck`로 강제됩니다.

## 5) 브랜치/커밋/PR 규칙 (Branch, Commit, PR Rules)

운영 효율과 변경 추적성을 위해 아래 규칙을 사용합니다.  
Follow these rules for traceable and reviewable changes.

### 브랜치/PR

- maintainer는 상황에 따라 `main`에 직접 반영할 수 있습니다.
- 리스크가 큰 변경, 다단계 변경, 협업 변경은 feature branch + PR을 권장합니다.
- 외부 기여자는 branch + PR을 기본으로 하며, PR 본문에 목적/영향/검증 결과를 포함합니다.

### 커밋 메시지

- Conventional Commits 형식을 사용합니다.
- 제목/본문은 한글로 작성합니다.
- 기본 형식: `type(scope): 요약`
- 하나의 커밋에는 하나의 의도만 담고, 서로 다른 관심사는 분리합니다.
- 본문은 문단 단위로 작성하고 문장별로 `-m`를 여러 번 나누지 않습니다.

권장 예시:

```bash
git commit -m "docs(contributing): 기여 가이드 문서 추가" -m "운영 정책, 검증 명령, 커밋/PR 규칙을 정리해 신규 기여자 진입 장벽을 낮춘다."
```

여러 줄 본문이 필요하면 zsh의 `$'...'` 인용을 권장합니다.

```bash
git commit -m "chore(ci): 웹 검증 단계 정리" -m $'- web lint/format 규칙 명시\n- CI typecheck 책임 구간 설명 추가'
```

## 6) CI 기준 (CI Expectations)

로컬 통과보다 CI 결과가 최종 기준입니다.  
CI is the source of truth when local and remote results differ.

PR/푸시에서 확인되는 핵심 체크:

- `CI / Ruff + Mypy + Pytest`
- `CI / Next.js Web (Lint + Typecheck + Test + Build)`
- `workflow_audit`
- `security_audit`

참고:

- Python/Web 품질 검증은 `.github/workflows/ci.yml`에서 수행됩니다.
- 워크플로/보안 감사는 `.github/workflows/audit.yml`에서 수행됩니다.

## 7) 보안/설정 주의사항 (Security & Config Notes)

설정 충돌과 시크릿 노출은 가장 흔한 운영 장애 원인입니다.  
Prevent secret leaks and config conflicts in both commits and PR descriptions.

- `.env`의 시크릿 값은 커밋하지 않습니다.
- `config.yaml`과 `.env`에 동일 키를 중복 정의하지 않습니다(충돌 시 실패).
- 토큰/키/실계좌성 값이 로그, 스크린샷, PR 본문에 노출되지 않게 확인합니다.
- 환경 변수는 가능한 `.env.example` 또는 문서 예시 형식으로만 공유합니다.

## 8) 문서 기여 규칙 (Docs Contribution)

문서 변경도 코드 변경과 동일하게 일관성이 중요합니다.  
Documentation changes should follow the same consistency standards as code changes.

- 문서 인덱스 구조는 `docs/README.md`를 기준으로 맞춥니다.
- 네이밍 규칙:
  - ADR: `docs/adr/ADR-XXXX-<slug>.md`
  - 리뷰: `docs/reviews/YYYY/review-YYYY-MM-DD.md`
  - 버전 스펙/계획: `spec-vX.Y*.md`, `plan-vX.Y.md`
- 문서 추가/이동 시 관련 인덱스 링크를 함께 갱신합니다.

## Public API / Interface / Type 변경 사항

- 이 기여 가이드 추가는 코드 레벨 Public API/인터페이스/타입 변경을 포함하지 않습니다.
- 문서 인터페이스 변경만 발생합니다: `CONTRIBUTING.md` 신규 추가.

## 문서 검증 체크리스트 (Validation Scenarios)

아래 체크를 통과하면 문서 목적을 충족한 것으로 봅니다.  
Use this checklist to validate that the guide is complete and actionable.

1. 초행 기여자가 이 문서만 보고 환경 준비와 품질 검증 명령을 실행할 수 있어야 합니다.
2. 문서의 명령어가 실제 도구체인(`uv`, `pre-commit`, `pnpm --dir web`)과 일치해야 합니다.
3. 커밋/검증 규칙이 `README.md`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`와 충돌하지 않아야 합니다.
4. `web/` 변경 시 pre-commit 대상(`lint`, `format:check`), `web/src/app/` 한정 route static check, CI 강제 검사(`typecheck`) 구간이 명확해야 합니다.
