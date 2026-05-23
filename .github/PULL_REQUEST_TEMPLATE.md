## 배경 / 목적

<!-- 왜 이 변경이 필요한지 간단히 작성하세요. -->

## 변경 내용

<!-- 주요 변경 사항을 불릿으로 작성하세요. -->
- [ ] 항목을 작성하세요.

## Public API / Interface / Type 변경 사항

<!-- 외부 동작/인터페이스/타입 영향이 있으면 명시하세요. 없으면 "없음"을 적어주세요. -->

## 영향 범위

- [ ] `sab/` (Python 애플리케이션)
- [ ] `web/` (Next.js 대시보드)
- [ ] `.github/workflows/` (CI/CD/운영 자동화)
- [ ] `docs/` (문서만 변경)
- [ ] 기타:

## 검증 방법

### 기본 품질 체크

- [ ] `UV_CACHE_DIR=.uv-cache uv run ruff check .`
- [ ] `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
- [ ] `UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml`
- [ ] `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`

### 선택 실행 (해당 시)

- [ ] `UV_CACHE_DIR=.uv-cache uv run python -m sab scan`
- [ ] `UV_CACHE_DIR=.uv-cache uv run python -m sab sell`
- [ ] `UV_CACHE_DIR=.uv-cache uv run python -m sab entry`
- [ ] `UV_CACHE_DIR=.uv-cache uv run python -m sab ai-brief --entry-report <path>`
- [ ] `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run --all-files`
- [ ] `pnpm --dir web run lint` (`web/` 변경 시)
- [ ] `pnpm --dir web run format:check` (`web/` 변경 시)

### 검증 결과 요약

<!-- 핵심 결과/실패 원인/우회 사항을 작성하세요. -->

## 보안 / 설정 점검

- [ ] 시크릿(토큰/키/실계좌성 값)을 코드, 로그, 스크린샷, PR 본문에 포함하지 않았습니다.
- [ ] `config.yaml`과 `.env` 간 동일 키 중복 여부를 확인했습니다.
- [ ] 서버 전용 키가 브라우저 코드로 노출되지 않음을 확인했습니다. (해당 시)

## 리뷰 포인트

<!-- 리뷰어가 집중해서 봐야 할 부분을 적어주세요. -->

## CI 체크 확인

- [ ] Python CI 통과 (`.github/workflows/ci.yml`)
- [ ] Web CI 통과 (`.github/workflows/ci.yml`)
- [ ] Workflow Audit 통과 (`.github/workflows/audit.yml`)
- [ ] Security Audit 통과 (`.github/workflows/audit.yml`)

## 스크린샷 / 아티팩트 (선택)

<!-- UI 변경, 리포트 산출물, 로그 링크 등을 첨부하세요. -->

## 관련 이슈

- Closes #
