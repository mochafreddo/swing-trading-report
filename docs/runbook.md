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
가짜 조언을 만들지 않고 sanitized `CONFIG_UNAVAILABLE`/exit 2로 닫힙니다. 이 경로는 기존
workflow gating이나 외부 알림에 연결되지 않습니다.

```bash
uv run python -m sab decision-board \
  --run-kind entry \
  --run-id entry-shadow-001 \
  --idempotency-key sha256:<64-lowercase-hex> \
  --created-at 2026-08-09T12:00:00Z \
  --sealed-input-hash sha256:<64-lowercase-hex>
```

### Decision Board local shadow RunJournal

`RunJournalV0`는 로컬 journal directory만 durable authority로 사용합니다. wrapper는 runner
호출 전에 expected identity를 원자적으로 claim합니다. grace가 이미 지난 slot은
`MISSED_EXPECTED`를 기록하고 runner를 호출하지 않으며, 유효한 slot만 호출 직전에
`STARTED`를 기록합니다. runner가 정상적인 sanitized 결과를 반환한
경우에만 `PUBLISHED`, `BLOCKED`, `FAILED` 중 하나로 compare-and-set 전이합니다. runner가
중단되거나 결과 계약을 반환하지 않으면 `STARTED`를 남기며, 별도 reconcile이 명시된 TTL 뒤
`STALE_INCOMPLETE`로 전이합니다. 실행이 시작되지 않은 명시적 expected slot은 grace 뒤
`MISSED_EXPECTED`가 됩니다. 각 record는 claim 시의 `grace_seconds`와 `stale_seconds`를
provenance로 보존하며, 이후 reconcile에서 다른 정책으로 재해석하면 conflict로 중단합니다.
journal에는 절대 경로, 계좌 식별자, provider 원문 오류를 쓰지 않습니다.

경로 authority는 filesystem root(`/`)의 read-only directory FD에 잡는 짧은 전역
`flock` 아래 journal 절대 경로의 모든 component를 `O_DIRECTORY|O_NOFOLLOW`로 순회해
각 dev/inode를 고정합니다. write 뒤 directory fsync와 마지막 full-chain/lock/target inode
검증이 모두 끝난 순간만 durable commit point입니다. 그 전의 pathname 교체는 pinned root의
변경을 rollback하고 실패합니다. store operation과 FD open은 단일 Python thread인 local CLI
process에서만 허용하며, 다중 thread가 감지되면 path open이나 directory 생성 전에 sanitized
오류로 중단합니다. 이 전제 아래 FD open은 `SIGKILL`/`SIGSTOP`을 제외한 모든 blockable signal을
잠시 차단해 반환된 정확한 FD의 ownership을 먼저 등록하고, signal mask 변경이 예외를 내면
알고 있던 이전 mask를 재적용·검증한 뒤 그 FD만 한 번 닫습니다. path-like 변환은 signal 차단
전에 끝냅니다. 이는 enforced single-thread local CLI boundary이며 일반적인 multi-thread process
전체의 signal/FD safety를 보장하지 않습니다. process-wide FD scan이나 닫힌 FD 번호 재시도는
다른 FD를 닫을 수 있어 사용하지 않습니다. close가 예외를 낸 경우에도 재시도하지 않고
`F_GETFD`로 이미 닫혔는지만 확인합니다. commit 뒤 unlock/close 오류의 완료 여부가 불확실하면 raw
오류 대신 `run_kind + expected_at + run_id + status`만 담은 sanitized committed-cleanup 오류를
냅니다. 안전한 정규식 이름의
orphan backup은 다음 lock 획득 때 inode/link-count를 확인해 삭제하고 개수만 로컬 로그에
남깁니다. 이 anchor는 서로 다른 journal directory의 짧은 local operation도 직렬화하는
보수적 tradeoff이므로 lock 내부에서 runner나 네트워크 작업을 수행하지 않습니다.

절대 경로 중간 ancestor는 macOS `O_SEARCH`(`O_DIRECTORY|O_NOFOLLOW`)로 열어 read 권한 없이
search 권한만 있는 `0111` directory도 정상 순회·재검증합니다. filesystem anchor와 실제
journal root만 각각 flock과 listing/write에 필요한 read FD로 엽니다.

공개 JSON Schema는 canonical 필드 형태를 검사하지만 timestamp 간 시간 순서는 표준 JSON
Schema만으로 완전히 표현하지 못합니다. Python 소비 경계는 반드시
`parse_run_journal_v0()`를 사용해 chronology를 포함한 semantic contract까지 검증해야 합니다.
Web mirror는 같은 chronology refinement를 적용합니다.
`report_file`이 존재하는 모든 상태 branch는 하나의 공유 basename schema를 사용하며 마지막
개행까지 거부합니다.

wrapper와 두 plist 파일은 shadow 검증용 템플릿일 뿐입니다.
`com.mochafreddo.sab.decision-board.{entry,holding}-shadow.plist.template`은
`Disabled=true`이고 실제 시간표가 없습니다. 저장소는 운영 wall-clock, 설치 경로,
`run_id`를 선택하거나 `launchctl`로 load하지 않습니다. 운영자가 별도 승인된 schedule을
정한 뒤에도 먼저 아래처럼 모든 UTC identity와 runner 인자를 직접 주입해 dry-run 합니다.

```bash
scripts/launchd/sab-decision-board-shadow-wrapper.sh \
  --run-kind ENTRY \
  --expected-at 2026-08-11T01:00:00Z \
  --run-id entry-shadow-example \
  --journal-dir logs/decision-board-journal \
  --grace-seconds 300 \
  --stale-seconds 1800 \
  --dry-run \
  -- uv run python -m sab decision-board \
    --run-kind ENTRY \
    --run-id entry-shadow-example \
    --idempotency-key sha256:<64-lowercase-hex> \
    --created-at 2026-08-11T01:00:00Z \
    --sealed-input-hash sha256:<64-lowercase-hex>
```

status는 bounded, 최신 expected slot 우선 순서의 sanitized JSON만 출력합니다.

```bash
uv run python -m sab decision-board-journal-status \
  --journal-dir logs/decision-board-journal \
  --limit 100
```

missed/stale 판정은 현재 시각까지 명시적으로 주입합니다. 다음 예시는 형식 설명용이며 운영
시간표가 아닙니다.

```bash
uv run python -m sab decision-board-journal-reconcile \
  --journal-dir logs/decision-board-journal \
  --run-kind ENTRY \
  --expected-at 2026-08-11T01:00:00Z \
  --run-id entry-shadow-example \
  --now 2026-08-11T01:30:01Z \
  --grace-seconds 300 \
  --stale-seconds 1800 \
  --limit 100
```

장애 시에는 먼저 관련 템플릿을 계속 disabled 상태로 두고 wrapper 호출을 중단합니다.
journal JSON을 수동 편집하거나 stale/missed 기록을 삭제해 재사용하지 않습니다. 다음 slot은
새 `expected_at + run_id` identity로 실행할 수 있습니다. 기능 rollback은 wrapper와 journal
CLI consumer를 제거하되 이미 기록된 local journal과 Decision Board report artifact를 보존하는
것입니다. 이 shadow lane은 외부 전송이나 주문 실행을 소유하지 않습니다.

## 필수 품질 게이트

```bash
just quality
just ci-web
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py -q
```

## 확인 필요

NEEDS_CONFIRMATION: 기존 runbook의 모든 세부 운영 문구가 실제 현재 운영 절차와 1:1로 동일한지는 소유자 확인이 필요합니다. 이 개편에서는 코드와 설정으로 확인 가능한 절차를 목적별 문서에 우선 반영했습니다.
