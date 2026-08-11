# Task 8 report — Decision Board runner and typed result aggregation

## 결과와 전파 경로

local-only Decision Board V0 runner를 다음 단방향 경계로 구현했다.

`exact trigger request -> shared preparation -> selected public item enrichment -> T6 pure compiler -> T1 envelope/hash validation -> T7 local atomic write -> optional upload -> typed terminal result`

- `DecisionRunRequestV0`는 exact `ENTRY|HOLDING`, public run identity, UTC timestamp, sealed input hash, issued full compiler universe, issued HOLDING selection, strict metadata를 process-local issuance에 결속한다.
- shared prerequisite만 `BLOCKED`; item timeout/provider/coverage failure는 freshly issued compiler item의 `REVIEW`; raw/mutated/wrong-lane/unexpected/internal/persistence failure는 `FAILED`다.
- `DecisionRunPublishedV0`, `DecisionRunBlockedV0`, `DecisionRunFailedV0`는 constructor-closed/factory-owned variant이고 public serializer는 status, exit, basename, storage key, safe issue code만 내보낸다.
- CLI `sab decision-board`는 explicit trigger identity와 upload mode만 받는다. production preparation/research adapter가 없는 기본 executor는 `CONFIG_UNAVAILABLE`로 fail closed하며 가짜 조언을 만들지 않는다.
- scheduler shadow seam은 `DISABLED` upload mode로 runner를 정확히 한 번 호출하고 기존 pipeline result object를 그대로 돌려준다.

## RED/GREEN 증거

| 단계 | RED | GREEN |
| --- | --- | --- |
| request/result authority | 신규 module 부재 `ModuleNotFoundError` 1 collection error | raw/fresh-equal/mutation/forgery 포함 3 passed |
| state/exit | `DecisionBoardRunnerV0`/PUBLISHED/BLOCKED import 부재 1 collection error | PUBLISHED/BLOCKED exit 0, FAILED exit 2, all-REVIEW/empty ENTRY 포함 5 passed |
| item isolation/universe | typed operational enrichment error import 부재 1 collection error | timeout item REVIEW + peer DECIDED, HOLDING 6개 full compile, hard SELL 유지 |
| compiler authority | valid하지만 request와 다른 sealed hash payload가 PUBLISHED되어 1 failed | identity parity 검사 후 FAILED/no write |
| adapter alias | local writer의 nested mutation이 result까지 전파되어 1 failed | writer graph deep-detach 후 authoritative envelope 보존 |
| CLI/scheduler | 신규 cli/scheduler module 부재 2 collection errors | safe args/default disabled/fail-closed, one-shot/non-gating/static proof |
| review: item error authority | issued TIMEOUT exception mutation/subclass가 BUY로 승격되어 2 failed | exact issued operational error와 REVIEW state만 격리, 나머지는 FAILED |
| review: compiler universe | foreign ENTRY, READY ENTRY 누락, HOLDING universe 누락이 저장되어 3 failed | ENTRY signal-derived exact set과 HOLDING full set을 write 전에 검증 |
| review: persistence/result | writer RuntimeError, equal string subclass, uploader file 삭제, incompatible result fields가 escape/수용 | 모든 `Exception`을 typed terminal로 수렴하고 T7 file/key/envelope identity 및 field 조합을 결속 |
| review: metadata/privacy | path/control/private version과 거짓 count, CLI absolute report dir가 public output에 남음 | safe version grammar, derived counts, public CLI path 제거 |
| final review: exact authority | request/result status/path/preparation의 equal subclass·삭제·runtime-error mutation이 오분류 또는 escape | 매 경계 exact validator 재실행, metadata identity binding, total snapshot validation, BaseException 보존 |
| final review: upload/CLI/directory | REQUIRED mode mutation, authoritative file delete/overwrite, argparse sentinel echo, report dir inode swap이 계약을 우회 | frozen mode, disposable exact upload copy, sanitized handler validation, directory dev/inode receipt binding |

최종 focused runner/CLI/scheduler 묶음은 `53 passed in 0.22s`였다.

## 상태와 exit 계약

| 상태 | 조건 | payload | local write | exit |
| --- | --- | --- | --- | --- |
| PUBLISHED | shared prerequisite valid, compile valid | exact payload/hash | yes | 0 |
| BLOCKED | shared prerequisite invalid/unavailable | absent | sanitized envelope yes | 0 |
| FAILED | config/authority/internal/persistence invariant | absent | invalid artifact no | 2 |

모든 eligible item이 `REVIEW`여도 shared prerequisite가 valid하면 PUBLISHED다. deterministic ENTRY signal이 모두 absent이면 items `[]` PUBLISHED다.

## Shared와 item failure 분류

- shared snapshot/preflight/version/candle prerequisite failure: `BLOCKED`, zero directional payload.
- one-item timeout/provider/no-source/coverage/stale/conflict: 해당 item `ResearchStateV0`를 보존한 `REVIEW`; peer compile 지속.
- unexpected adapter exception, raw/same/wrong deterministic result, compiler identity mismatch: `FAILED`, no write.
- `BaseException`은 business result로 catch하지 않는다.

## Hard SELL과 full universe 증거

6개 HOLDING fixture에서 selection은 1–5번 item만 enrichment 호출했다. compiler에는 6개 전체 universe가 전달되며 cap 밖 6번째 hard-stop은 `DECIDED/SELL`로 남았다. selected hard SELL도 operational research timeout 이후 `SELL`을 유지한다.

## Persistence/upload 순서와 replay

| local | upload mode/result | terminal |
| --- | --- | --- |
| fail | any | FAILED, upload 0회 |
| success | disabled | PUBLISHED/BLOCKED, `storage_key=None` |
| success | optional success | exact T7 key |
| success | optional fail/mismatch | PUBLISHED/BLOCKED degraded + `UPLOAD_FAILED` |
| success | required fail/mismatch | FAILED + retained local basename/path |

event recorder로 local-before-upload 순서를 증명했다. 같은 exact request replay는 같은 path/key/bytes를 반환한다. 같은 deterministic identity의 다른 bytes는 T7 typed idempotency conflict로 FAILED하며 suffix나 추가 upload를 만들지 않는다. writer에게는 deep-detached graph만 전달하고 returned local bytes/path와 upload key를 exact T7 identity에 다시 대조한다.

upload adapter에는 authoritative T7 path 대신 canonical bytes로 만든 disposable copy만 전달한다. 따라서 adapter가 copy를 삭제/overwrite하고 실패해도 OPTIONAL은 exact local PUBLISHED/BLOCKED degraded, REQUIRED는 exact retained basename이 있는 UPLOAD_FAILED다. upload mode는 adapter 호출 전 exact snapshot으로 고정하고 호출 뒤 request authority를 재검증한다. report directory는 writer 호출 전후와 upload 뒤 `lstat` device/inode가 같아야 하며 symlink 또는 교체는 LOCAL_PERSISTENCE_FAILED다.

## Privacy, advice-only, notification-free 증거

- enrichment request는 run kind, item ID, T3 public six-field instrument만 가진다.
- strict envelope metadata allowlist 외 account/quantity/entry price/P&L/notes/tags/private values를 거부한다.
- exception string, traceback, absolute local path, env/account/provider raw value를 result/CLI JSON에 직렬화하지 않는다.
- private sentinel adapter exception은 safe issue code로만 노출되며 artifact/error output에 나타나지 않았다.
- scheduler source static test는 Telegram/Slack send 및 order create/modify/cancel/conditional call token 부재를 확인한다.
- 기존 scan/sell/AI Brief pipeline result identity와 return contract는 shadow seam이 변경하지 않는다.

## 회귀와 정적 검증

- review fix 전 focused + T1-T7 + legacy CLI/scheduler/storage: `596 passed in 1.90s`.
- final review fix 후 T1-T7 + legacy CLI/scheduler/storage 확대 회귀: `689 passed in 17.75s`.
- multiprocessing storage 회귀에서 package eager export가 순환 import를 만들었고 root export를 제거한 뒤 실패했던 2 tests는 `2 passed`.
- 신규 source mypy: `Success: no issues found in 5 source files`.
- 신규 source/tests ruff: `All checks passed!`.
- final review fix 후 full `UV_CACHE_DIR=.uv-cache mise exec -- just quality`: ruff clean, 302 files format-clean, mypy 289 source files clean, pytest `2935 passed, 8 skipped` in 56.56s. 초기 구현 full gate의 신규 test helper type 15건과 final adversarial Path probe의 좁은 mypy annotation 1건은 의도에 맞게 교정한 뒤 해결했다.
- `git diff --check`: clean.

Web/schema 파일은 변경하지 않았으므로 Task 8 지시에 따라 `just ci-web`은 실행하지 않는다. shared schema/Web mirror는 T1/T7 회귀로 보존했다.

## Rollout, rollback, 남은 불확실성

rollout은 local CLI contract 확인 -> production public-data preparation/research adapter 별도 승인/구현 -> T9 RunJournal/launchd shadow 연결 -> shadow 관측 순서다. rollback은 CLI dispatch와 scheduler shadow consumer 및 Task 8 modules만 제거하고 T1-T7 schema/compiler/storage artifact는 유지한다. local artifact가 upload보다 authoritative하므로 optional upload 장애에서 재시도 가능하다.

남은 범위는 의도적이다. production provider/verifier/source adapter, BrokerSnapshot runtime wiring, live Supabase round-trip, T9 RunJournal/launchd/missed-stale visibility, T10 Web detail UI는 구현하지 않았다. live provider, Toss, browser, order method는 호출하지 않았다.
