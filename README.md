# Swing Trading Report

상태: Accepted (프로젝트 진입점)

KR/US 시장용 on-demand 스윙 트레이딩 신호 스캐너와 로컬 운영 콘솔입니다. Python 패키지 `sab`가 `buy`/`sell`/`entry`/`backtest`/`ai-brief`/`sell-ai-brief` JSON 리포트를 만들고, Next.js 웹 UI가 Supabase에 저장된 리포트와 보유 목록을 보여줍니다. `backtest`는 로컬 historical OHLCV 연구 산출물입니다. US SWING Decision Board V0의 schema/compiler/runner/storage/UI와 explicit live-shadow adapter는 advice-only로 구현됐고, 승인된 기간 한정 exact-slot heartbeat가 20-session gate를 누적합니다. 기본 CLI와 launchd template은 비활성이고 fail closed입니다. GitHub Actions는 CI/audit/release, cleanup, manual dispatch, AI Brief monitor/fallback을 담당합니다. Scheduled scan은 marker-aware fallback 전까지 fail closed이고, scheduled Sell AI Brief generation은 Toss freshness marker가 있을 때 로컬 generic wrapper가 실행합니다.

## 문서 상태

### 현재 제공

- 프로젝트 개요, 빠른 시작, 핵심 명령, 문서 지도만 제공합니다.
- 상세한 개발, 설정, 배포, 운영, 장애 대응, API, 전략 문서는 `docs/` 아래 문서로 분리합니다.

### 실험

- 별도 실험 전용 사용자 기능은 현재 운영 기준에 포함하지 않습니다.
- 전략/파라미터 실험은 `docs/STRATEGY.md`, replay fixture, 테스트에서 추적합니다.

### 백로그

- standalone `entry` workflow dispatch와 웹 `Run` 탭 연결은 backlog입니다.
- 원격 공개 운영 모델은 별도 보안/권한 설계 전까지 범위 밖입니다.

### 폐기 후보

- `watchlist.yaml` 메모형 입력 포맷과 현재 저장소 구조와 맞지 않는 초기 bootstrap 설명은 유지하지 않습니다.

## 빠른 시작

```bash
mise install
UV_CACHE_DIR=.uv-cache uv sync --all-extras --all-groups
cp .env.example .env
```

`.env`에는 실제 시크릿을 넣되 커밋하지 마세요. 최소 KIS 실행에는 `KIS_APP_KEY`, `KIS_APP_SECRET`이 필요하고, 웹 UI와 업로드에는 Supabase와 관리자 로그인 환경변수가 필요합니다. 전체 설정 표는 [docs/configuration.md](docs/configuration.md)를 보세요.

## 핵심 명령

```bash
just --list
just scan --universe both
just sell
just entry
UV_CACHE_DIR=.uv-cache uv run python -m sab backtest --data-file data/history.json --tickers AAPL.NAS --assumptions-file data/backtest-assumptions.json
UV_CACHE_DIR=.uv-cache uv run python -m sab ai-brief --entry-report reports/YYYY-MM-DD.entry.json
docker compose up -d --build web
```

AI Brief가 source URL 본문 확인까지 수행해야 하면 `lightpanda`가 실행 환경의 `PATH`에 있는 상태에서 `--article-reader lightpanda`를 추가합니다. 이 reader는 공개 URL을 보수적으로 읽어 `article_read` 메타데이터만 붙이며, paywall/CAPTCHA/ 로그인/robots/bot block/접근 제어를 우회하지 않습니다.

웹 UI 기본 주소는 `http://localhost:${WEB_HOST_PORT}`이며 기본 포트는 `55300`입니다.

## 품질 검증

```bash
just quality
just ci-web
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py -q
```

Python-only 변경은 `just quality`, 웹 변경은 `just ci-web`, 문서 구조 변경은 `tests/test_docs_state_contract.py`를 우선 실행합니다. 웹 UI나 인증/라우팅에 영향을 줄 수 있는 변경은 로컬 `sab-web`에서 브라우저 smoke도 남깁니다. QA 리포트와 스크린샷 같은 로컬 검증 산출물은 `.gstack/qa-reports/`에 두며 git에는 커밋하지 않습니다.

## 기술 스택

| 영역 | 스택 |
| --- | --- |
| Python engine | Python 3.14, `uv`, `requests`, `PyYAML`, optional `pykrx` |
| Web console | Next.js 16, React 19, TypeScript, pnpm |
| Storage/backend | Supabase Postgres, Supabase Storage |
| Automation | GitHub Actions, Docker Compose, macOS `launchd` scheduled AI Brief, Toss daily holdings sync, Toss-gated scheduled Sell AI Brief generation; scheduled scan fail-closed guard |
| Toolchain | `mise`, `just`, Ruff, Mypy, Pytest, ESLint, Vitest, Prettier |

## 문서 지도

| 질문 | 문서 |
| --- | --- |
| 처음 온 개발자가 어디서부터 읽을지 | [docs/README.md](docs/README.md) |
| 이 시스템이 무엇을 하는가 | [docs/overview.md](docs/overview.md) |
| 로컬에서 설치/실행/테스트하려면 | [docs/local-development.md](docs/local-development.md) |
| 환경변수와 config 키는 무엇인가 | [docs/configuration.md](docs/configuration.md) |
| 전체 구조와 데이터 흐름은 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| CLI와 웹 API는 어떻게 생겼나 | [docs/api.md](docs/api.md) |
| 배포/마이그레이션/롤백은 | [docs/deployment.md](docs/deployment.md) |
| 운영 체크와 로그/헬스체크는 | [docs/operations.md](docs/operations.md) |
| 기존 runbook 링크나 운영 시작점은 | [docs/runbook.md](docs/runbook.md) |
| 장애가 나면 어디서부터 보는가 | [docs/troubleshooting.md](docs/troubleshooting.md) |
| 전략 신호와 리스크 규칙은 | [docs/STRATEGY.md](docs/STRATEGY.md) |
| Decision Board V0 계약과 현재 상태는 | [docs/decision-board.md](docs/decision-board.md) |
| Decision Board shadow를 어떻게 평가하는가 | [docs/decision-board-shadow-evaluation.md](docs/decision-board-shadow-evaluation.md) |
| Today 보드와 미분류 로컬 미리보기를 어떻게 사용하는가 | [docs/today-decision-board.md](docs/today-decision-board.md) |
| 기여/커밋/검증 규칙은 | [docs/contributing.md](docs/contributing.md) |
| 보안 신고와 시크릿 사고 대응은 | [SECURITY.md](SECURITY.md) |

## 주요 산출물

- 로컬 리포트: `reports/YYYY-MM-DD(-n).{buy|sell|entry|backtest|ai-brief|ai-brief-skip|sell-ai-brief}.json`
- Decision Board local report: `reports/YYYY-MM-DD.decision-board.{entry|holding}.<run_id>.<64hex>.json`
- Supabase Storage key: `YYYY/MM/YYYY-MM-DD(-n).{buy|sell|entry|ai-brief|ai-brief-skip|sell-ai-brief}.json`
- 보유 목록 source of truth: Supabase `holdings`
- 리포트 목록 source of truth: Supabase `report_index`
- 런타임 상태/락 source of truth: Supabase `runtime_state`
- 로컬 QA 산출물: `.gstack/qa-reports/`(리포트, baseline, 스크린샷; gitignore 대상)

## 보안 기본값

- `.env`, `.env.*`, `.envrc.local`, `holdings.yaml`, `watchlist.txt`, `data/`, `reports/`는 커밋하지 않습니다.
- `config.yaml`은 비시크릿 기본값만 담습니다.
- `config.yaml`과 `.env`에 동일 논리 키를 중복 정의하면 fail-closed로 실패합니다.
- 서버 전용 키(`SUPABASE_SECRET_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `GITHUB_PAT`)는 브라우저 코드로 노출하지 않습니다.

## 라이선스

[LICENSE](LICENSE)를 참고하세요.
