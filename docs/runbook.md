# Runbook

상태: Accepted (호환 진입점)

이 파일은 기존 링크를 깨지 않기 위해 유지하는 운영 runbook 진입점입니다. 현재 세부 운영 절차는 목적별 문서로 분리했습니다.

## 문서 상태

### 현재 제공

- 운영 문서의 시작점과 legacy runbook 내용이 이동된 위치를 제공합니다.
- 기존 `docs/runbook.md` 링크 사용자를 새 문서 구조로 안내합니다.

### 실험

- 별도 실험 절차는 이 파일에 추가하지 않습니다.

### 백로그

- 기존 긴 runbook의 상세 절차 중 현재 코드와 재검증이 필요한 항목은 목적별 문서로 흡수하거나 archive 후보로 분류합니다.

### 폐기 후보

- 이 파일에 설치/운영/API/장애 대응 상세를 계속 중복 유지하는 방식은 폐기 후보입니다. 삭제는 사용자 명시 승인 전까지 하지 않습니다.

## 어디서부터 볼 것인가

| 상황 | 현재 문서 |
| --- | --- |
| 처음 프로젝트 파악 | [overview.md](overview.md) |
| 로컬 설치/실행/테스트 | [local-development.md](local-development.md) |
| 환경변수와 config | [configuration.md](configuration.md), [config-reference.md](config-reference.md) |
| CLI와 웹 API | [api.md](api.md) |
| Docker/GitHub Actions/Supabase 배포 | [deployment.md](deployment.md) |
| 운영 체크, 로그, 헬스체크 | [operations.md](operations.md) |
| 장애 증상별 대응 | [troubleshooting.md](troubleshooting.md) |
| 아키텍처와 데이터 흐름 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 전략 신호/리스크 로직 | [STRATEGY.md](STRATEGY.md) |
| 기여/검증 규칙 | [contributing.md](contributing.md) |

## 빠른 운영 시작점

```bash
docker compose ps
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/login
gh run list --limit 10
```

Decision Board V0 command boundary 확인은 local-only이며 기본 upload mode는 `disabled`입니다.
현재 production preparation/research adapter가 의도적으로 미설정되어 있어 아래 형식의 실행은
가짜 조언을 만들지 않고 sanitized `CONFIG_UNAVAILABLE`/exit 2로 닫힙니다. T9 전에는 launchd,
RunJournal, 알림, 기존 workflow gating에 연결하지 않습니다.

```bash
uv run python -m sab decision-board \
  --run-kind entry \
  --run-id entry-shadow-001 \
  --idempotency-key sha256:<64-lowercase-hex> \
  --created-at 2026-08-09T12:00:00Z \
  --sealed-input-hash sha256:<64-lowercase-hex>
```

## 필수 품질 게이트

```bash
just quality
just ci-web
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py -q
```

## 확인 필요

NEEDS_CONFIRMATION: 기존 runbook의 모든 세부 운영 문구가 실제 현재 운영 절차와 1:1로 동일한지는 소유자 확인이 필요합니다. 이 개편에서는 코드와 설정으로 확인 가능한 절차를 목적별 문서에 우선 반영했습니다.
