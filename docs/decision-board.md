# Decision Board V0 Reference

상태: Accepted (구현 완료, production adapter 미연결 shadow)

Decision Board V0는 기존 로직이 만든 US SWING 후보와 확인된 SWING 보유 종목을
공개 근거로 보강해 `BUY|AVOID|REVIEW` 또는 `HOLD|SELL|REVIEW` 조언을 만드는
로컬 shadow 경계입니다. 사용자가 모든 매수·매도를 직접 실행합니다. 이 기능에는
주문 생성·수정·취소, 조건부 주문, 알림 전송 권한이 없습니다.

현재 schema, identity gate, research/claim validation, compiler, runner, atomic report
storage, RunJournal, Reports UI와 검증 스위트는 구현되어 있습니다. 다만 기본 CLI의
production preparation/research/claim-verifier adapter는 의도적으로 연결되지 않았습니다.
따라서 저장소 기본 상태의 `sab decision-board`는 조언을 추측하지 않고
`CONFIG_UNAVAILABLE`, exit 2로 종료합니다. 실제 shadow 측정 기간은 approved adapter가
별도 검증·연결된 뒤에만 시작할 수 있습니다.

## 범위

| 포함 | 제외 |
| --- | --- |
| US ENTRY SWING 후보 | KR 시장 |
| confirmed + exact `strategy=SWING` HOLDING | LONG_TERM 판단과 mandate engine |
| 공개 종목 identity와 공개 기사 | 계좌 번호, 수량, 단가, 손익, 메모, tag의 model 전달 |
| 최대 5종목 bounded research, full holding compile | 상시 자율 agent, portfolio optimizer |
| advice-only JSON report와 Web detail | 주문·알림·GitHub Actions production sidecar |
| local-only RunJournal shadow 관측 | 자동 launchd 설치/활성화 |

## 실행 흐름

```text
Toss holdings RPC + deterministic signal facts
  -> BrokerSnapshotV0 seal/freshness/digest/revision validation
  -> public InstrumentRefV0 + exact SWING/ENTRY gate
  -> bounded public research + safe article fetch
  -> exact-span claim validation
  -> pure ENTRY/HOLDING compiler
  -> decision-board.v0 envelope + canonical payload hash
  -> atomic local report
  -> optional Supabase Storage/report_index
  -> strict Reports API/UI projection

local launchd wrapper
  -> RunJournal STARTED
  -> runner terminal PUBLISHED|BLOCKED|FAILED
  -> RunJournal terminal observation
```

`BLOCKED`는 shared dependency가 안전하지 않아 방향성 조언을 만들지 못했다는 정상
shadow 결과이며 exit 0입니다. 종목별 timeout/coverage gap은 해당 종목 `REVIEW`로
격리됩니다. authority, schema, compiler, persistence invariant 오류는 `FAILED`, exit 2이며
invalid report를 게시하지 않습니다.

## Compiler truth table

### ENTRY

1. item 또는 identity 미승인: `REVIEW`
2. 확정 non-candidate signal: payload에서 제외
3. mandate/signal/price/exposure 입력 gap: `REVIEW`
4. deterministic exposure fail: `AVOID`
5. research gap/conflict: `REVIEW`
6. action-eligible `MATERIAL_ADVERSE`: `AVOID`
7. 나머지: `BUY`

### HOLDING

1. current deterministic hard stop/confirmed exit: `SELL`
2. item/identity/deterministic input gap: `REVIEW`
3. action-eligible material adverse: `REVIEW`
4. research gap/error: `REVIEW`
5. 나머지: `HOLD`

HOLDING research queue는 최대 5개지만 compiler는 모든 eligible SWING holding을
평가합니다. queue 밖 hard `SELL`도 `NOT_SELECTED_CAP`이나 evidence 상태로 낮아지지
않습니다.

## Evidence contract

- research 입력은 public `InstrumentRefV0`와 allowlisted question뿐입니다.
- URL은 canonical public-DNS HTTPS, query/userinfo/port/fragment 없음, 최대 2048 bytes입니다.
- search, retry, DNS, redirect, fetch, claim validation은 같은 monotonic 45초 deadline을
  사용합니다.
- action-changing evidence는 unchanged issued claim의 exact `SUPPORTED`, article content
  hash, exact supporting span/location, source identity가 모두 맞아야 합니다.
- public EvidenceRef는 role, source URL, publisher, publication time, freshness, citation,
  `SUPPORTED`, article hash, exact span/location을 포함합니다.
- 모델/provider의 raw error, traceback, 로컬 path, 비공개 URL은 report/API/UI에
  투영하지 않습니다.

## Report contract

| 항목 | 계약 |
| --- | --- |
| schema | `decision-board.v0` |
| lane | exact `ENTRY|HOLDING` |
| payload identity | canonical JSON bytes + `sha256:` hash |
| replay | 같은 sealed input은 byte-identical payload/hash |
| local filename | `YYYY-MM-DD.decision-board.<entry|holding>.<run_id>.<64hex>.json` |
| Storage key | `YYYY/MM/<local filename>` |
| list identity | `run_kind + run_id + idempotency_key + decision_created_at` |
| local persistence | no-overwrite atomic write, same identity/same bytes idempotent |
| upload | local-first; optional failure degraded, required failure retained local artifact |

Web detail은 Storage exact bytes를 1 MiB로 제한하고 fatal UTF-8, duplicate JSON key,
schema, recomputed payload hash, Storage key identity를 검증합니다. API는 public allowlist
projection을 새로 만들며 invalid/private-bearing artifact는 sanitized 422로 끝납니다.

## CLI reference

기본 executor는 production adapter가 없으므로 항상 fail closed합니다. 아래 명령은
형식 확인용이며 실제 조언 생성 예시가 아닙니다.

```bash
uv run python -m sab decision-board \
  --run-kind ENTRY \
  --run-id entry-shadow-example \
  --idempotency-key sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --created-at 2026-08-13T01:00:00Z \
  --sealed-input-hash sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  --upload-mode disabled \
  --report-dir reports
```

| Flag | 값/제약 | 기본값 |
| --- | --- | --- |
| `--run-kind` | `ENTRY|HOLDING` | required |
| `--run-id` | `[A-Za-z0-9][A-Za-z0-9_-]{0,127}` | required |
| `--idempotency-key` | `sha256:` + 64 lowercase hex | required |
| `--created-at` | UTC timestamp | required |
| `--sealed-input-hash` | `sha256:` + 64 lowercase hex | required |
| `--upload-mode` | `disabled|optional|required` | `disabled` |
| `--report-dir` | local report directory | `reports` |

RunJournal status/reconcile/wrapper 명령은 [Runbook](runbook.md)을 참고하세요. 환경변수는
[Configuration](configuration.md), shadow 평가와 졸업 기준은
[Decision Board shadow evaluation](decision-board-shadow-evaluation.md)을 참고하세요.

## 활성화하지 않는 롤백

shadow 문제를 발견하면 launchd template을 `Disabled=true`로 유지하고 wrapper 호출을
중지합니다. report/journal을 수동 수정하거나 삭제해 통계를 좋게 만들지 않습니다.
다음 slot은 새 identity로 실행하고 차이는 `BUG` 또는 `UNEXPLAINED`로 기록합니다.
schema/migration처럼 기존 consumer와 호환되는 additive producer는 자동 삭제하지 않습니다.

## Related

- [Strategy](STRATEGY.md)
- [Architecture](ARCHITECTURE.md)
- [Runbook](runbook.md)
- [Configuration](configuration.md)
- [Shadow evaluation how-to](decision-board-shadow-evaluation.md)
