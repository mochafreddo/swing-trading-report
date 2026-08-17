# Decision Board V0 Reference

상태: Accepted (explicit live-shadow adapter 구현, schedule 비활성)

Decision Board V0는 기존 로직이 만든 US SWING 후보와 확인된 SWING 보유 종목을
공개 근거로 보강해 `BUY|AVOID|REVIEW` 또는 `HOLD|SELL|REVIEW` 조언을 만드는
로컬 shadow 경계입니다. 사용자가 모든 매수·매도를 직접 실행합니다. 이 기능에는
주문 생성·수정·취소, 조건부 주문, 알림 전송 권한이 없습니다.

현재 schema, identity gate, research/claim validation, compiler, runner, atomic report
storage, RunJournal, Reports UI와 검증 스위트는 구현되어 있습니다.
`DecisionBoardProductionAdapterV0`는 CLI identity와 sealed request를 대조합니다.
`DecisionBoardProductionComponentsV0`는 request loader, sealed preparer, public-only
enricher와 optional uploader를 기존 CLI executor에 명시적으로 조립합니다. request source에는
report 경로를 제외한 공개 trigger identity만 전달하고, evidence source에는 공개
`run_kind/item_id/InstrumentRefV0`만 전달합니다. ENTRY/HOLDING의 deterministic facts는
`PublicDecisionItemEnricherV0`가 원본 그대로 재발급하며, source는 typed research state와
검증된 evidence만 돌려줄 수 있습니다. 이 경로는 recorded Responses fixture로 canonical report
게시까지 검증합니다. component bundle은 세 least-authority wrapper의 exact type과 내부
request/evidence source capability를 조립 시점에 검증하며 raw loader, preparer, enricher를
허용하지 않습니다. 기존 직접 `adapter=` 주입은 낮은 수준의 호환 seam으로만 유지됩니다.

기존 `sab decision-board`와 dependency-injected composition seam은 계속 환경변수나
credential을 읽지 않으며 기본 상태에서 `CONFIG_UNAVAILABLE`, exit 2로 닫힙니다. 별도
`sab decision-board-shadow-live`만 명시적 live composition root를 사용합니다. 이 경로는
content-addressed Supabase Storage input snapshot, Finnhub/Polygon/Benzinga source chain,
public-DNS + pinned-address article fetch, OpenAI Responses claim verifier와 optional Supabase
report uploader를 조립합니다. launchd template과 shadow gate manifest는 여전히 비활성/
`PENDING`이며, recorded/live 비교와 별도 일정 승인이 끝나기 전에는 측정 기간으로 세지 않습니다.

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
  사용합니다. blocking DNS/HTTP/Responses/Supabase 작업은 kill 가능한 child process에서
  실행하므로 socket이나 executor thread가 timeout 뒤 남아 전체 wall-clock budget을 넘지
  않습니다. child environment는 비우며 news loader에는 해당 provider credential 하나만
  명시적으로 전달합니다.
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
| provider observations | provider별 attempts/failures/timeouts count만 public metadata에 기록 |

Web detail은 Storage exact bytes를 1 MiB로 제한하고 fatal UTF-8, duplicate JSON key,
schema, recomputed payload hash, Storage key identity를 검증합니다. API는 public allowlist
projection을 새로 만들며 invalid/private-bearing artifact는 sanitized 422로 끝납니다.

## CLI reference

기본 executor에는 adapter나 component bundle이 주입되지 않으므로 항상 fail closed합니다.
component bundle은 애플리케이션 코드가 승인된 외부 경계를 명시적으로 주입할 때만 사용할 수
있으며 CLI flag나 환경변수로 자동 구성되지 않습니다. 아래 명령은 형식 확인용이며 실제 조언
생성 예시가 아닙니다. recorded 검증은
`tests/test_decision_board_production_adapter.py`가 소유하며 live provider나 credential을
사용하지 않습니다.

live composition은 기존 `EvidenceResearcherV0`를 batch owner로 재사용합니다. 선택된 최대
5종목을 한 번에 전달하고 provider concurrency, URL dedupe, 전체 article cap을 보존하며,
같은 invocation-owned deadline을 claim validation까지 전달한 뒤 mapping-backed synchronous
item enricher로 기존 runner에 되돌립니다. shared verifier preflight 실패는 방향성 결과를
만들지 않는 `BLOCKED`로 닫힙니다.

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

live transport를 명시적으로 선택할 때만 command를 바꿉니다. 승인된 gate의 canonical
manifest와 private input/expected-action ledger 경로 및 `--gate-manifest-sha256`가 모두
필요합니다. runner는 승인 상태, content-bound approval signature, exact slot, 현재 Git/artifact/
model digest, ledger hash/count, sealed input membership을 provider 호출 전에 재검증합니다.
`sealed_input_hash`에 해당하는 public snapshot이 먼저 Supabase Storage의
`decision-board-inputs/v0/<64hex>.json`에 immutable canonical JSON으로 존재해야 합니다.
snapshot exact field set은 `schema`, `run_kind`, `metadata`, `items`이며 ENTRY/HOLDING item은
compiler의 public deterministic enum과 `InstrumentRefV0`만 포함합니다. quantity, entry price,
P/L, notes, tags, account field나 unknown field는 전체 snapshot을 거부합니다. snapshot은
manifest hash를 포함하지 않은 canonical bytes로 content-addressing합니다. 승인 manifest가
input ledger의 snapshot hash를 결속하고, 검증된 manifest hash는 실행 뒤 report metadata에
별도로 기록하므로 hash dependency는 단방향입니다.

```bash
uv run python -m sab decision-board-shadow-live \
  --run-kind ENTRY \
  --run-id entry-shadow-example \
  --idempotency-key sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --created-at 2026-08-13T01:00:00Z \
  --sealed-input-hash sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  --gate-manifest config/decision-board-shadow-gate.approved.local.json \
  --gate-manifest-sha256 sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc \
  --input-ledger /private/path/decision-board-shadow-input-ledger.json \
  --expected-action-ledger /private/path/decision-board-shadow-expected-action-ledger.json \
  --upload-mode disabled \
  --report-dir reports
```

필수 runtime 설정은 server-side Supabase key, `FINNHUB_API_KEY`, `POLYGON_API_KEY`,
`BENZINGA_API_TOKEN`, `OPENAI_API_KEY`, 그리고 `DECISION_BOARD_OPENAI_MODEL` 또는
`OPENAI_AI_BRIEF_MODEL`입니다. 하나라도 없으면 snapshot/provider 호출 전에
`CONFIG_UNAVAILABLE`로 닫힙니다. 이 명령은 주문·알림 capability를 import하거나 호출하지
않습니다. manifest/ledger/slot/runtime 및 snapshot hash/item membership 중 하나라도 다르면
`PREPARATION_INVALID`로 닫힙니다.

현재 vendor news chain은 검증 가능한 공개 기사 후보를 `PRIMARY` coverage로만 제공합니다.
opposing/action-changing source 의미를 추측하지 않으므로 claim verification이 성공해도
`COVERAGE_GAP`으로 남아 해당 종목은 `REVIEW`입니다. recorded/live comparison에서 별도
semantic search adapter가 검증되기 전에는 이 상태를 `CLEAR`나 방향성 근거로 승격하지 않습니다.

| Flag | 값/제약 | 기본값 |
| --- | --- | --- |
| `--run-kind` | `ENTRY|HOLDING` | required |
| `--run-id` | `[A-Za-z0-9][A-Za-z0-9_-]{0,127}` | required |
| `--idempotency-key` | `sha256:` + 64 lowercase hex | required |
| `--created-at` | UTC timestamp | required |
| `--sealed-input-hash` | `sha256:` + 64 lowercase hex | required |
| `--gate-manifest` | approved local gate JSON | live required |
| `--gate-manifest-sha256` | approved manifest canonical SHA-256 | live required |
| `--input-ledger` | private canonical input ledger JSON | live required |
| `--expected-action-ledger` | private canonical non-empty action-set ledger JSON | live required |
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
