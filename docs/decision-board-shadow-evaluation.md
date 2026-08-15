# How to evaluate and graduate the Decision Board shadow

상태: Accepted (수동 gate 절차)

이 절차는 US SWING ENTRY/HOLDING Decision Board를 최소 20 US 거래일 동안 기존
판단 경로와 나란히 관찰하고, 차이를 사전에 승인한 기준으로 분류해 다음 cutover 검토
자격이 있는지 판단합니다. **통과는 자동 활성화가 아닙니다.** launchd schedule, 알림,
GitHub Actions sidecar, 주문 권한은 별도 명시 승인 없이는 계속 비활성입니다.

## Prerequisites

- T1–T11 contract, privacy, no-order, workflow isolation, Python/Web gate가 green입니다.
- production preparation, research, claim-verifier adapter가 recorded/live comparison을 거쳐
  별도 승인·연결되어 있습니다. 기본 `CONFIG_UNAVAILABLE` executor 상태에서는 측정이
  시작되지 않습니다.
- `BrokerSnapshotV0` migration/Web producer/Python consumer 순서가 완료되고 ENTRY/HOLDING
  input identity가 확정돼 있습니다.
- launchd template은 여전히 `Disabled=true`입니다. 운영자가 승인한 외부 schedule에서만
  wrapper를 호출합니다.
- 실제 주문, 알림, Toss mutation, GitHub Actions production sidecar가 없음을 capability와
  workflow test로 확인했습니다.
- 평가 manifest를 첫 실행 전에 사람이 승인했습니다.

## 1. Freeze the gate manifest

Gitignore된 로컬 파일에 다음 항목을 기록하고 기간 중 덮어쓰지 않습니다.

```json
{
  "gate_version": "us-swing-shadow-v1",
  "start_session": "YYYY-MM-DD",
  "minimum_sessions": 20,
  "lanes": ["ENTRY", "HOLDING"],
  "policy_versions": {
    "compiler": "approved-version",
    "researcher": "approved-version",
    "verifier": "approved-version"
  },
  "expected_slots": [],
  "allowed_diff_reasons": [
    "EXPECTED_POLICY_CHANGE",
    "INPUT_GAP",
    "SOURCE_GAP",
    "BUG",
    "UNEXPLAINED"
  ],
  "approved_thresholds": {
    "unexplained": 0,
    "privacy_leaks": 0,
    "order_or_notification_accesses": 0,
    "payload_replay_mismatches": 0,
    "uncovered_eligible_holdings": 0
  }
}
```

`expected_slots`에는 lane, UTC expected time, run ID 생성 규칙을 적습니다. provider
failure-rate나 source coverage에 숫자 threshold가 필요하면 첫 실행 전에 manifest에
추가합니다. 관찰 결과를 본 뒤 threshold를 낮추는 것은 허용하지 않습니다. 기준을
바꾸려면 새 `gate_version`으로 전체 기간을 다시 시작합니다.

Manifest에 실제 계좌 번호, 수량, 단가, 손익, 메모, tag, credential을 넣지 않습니다.

## 2. Dry-run one ENTRY and one HOLDING slot

RunJournal wrapper 형식과 identity만 먼저 확인합니다.

```bash
scripts/launchd/sab-decision-board-shadow-wrapper.sh \
  --run-kind ENTRY \
  --expected-at 2026-08-13T01:00:00Z \
  --run-id entry-shadow-example \
  --journal-dir logs/decision-board-journal \
  --grace-seconds 300 \
  --stale-seconds 1800 \
  --dry-run \
  -- uv run python -m sab decision-board \
    --run-kind ENTRY \
    --run-id entry-shadow-example \
    --idempotency-key sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
    --created-at 2026-08-13T01:00:00Z \
    --sealed-input-hash sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
    --upload-mode disabled
```

HOLDING도 별도 run ID와 `--run-kind HOLDING`으로 반복합니다. dry-run이 runner를 호출하거나
report를 만든다면 중단합니다.

## 3. Capture every planned session

각 US 거래일에 ENTRY와 HOLDING을 독립 slot으로 실행합니다. 같은 session에서 한 lane의
실패가 다른 lane이나 기존 scan/sell/AI Brief 결과를 바꾸면 gate 실패입니다.

```bash
uv run python -m sab decision-board-journal-status \
  --journal-dir logs/decision-board-journal \
  --limit 100 \
  --scan-limit 1000 \
  --max-record-bytes 65536 \
  --max-output-bytes 262144
```

매 slot에 대해 다음만 평가 ledger에 기록합니다.

- session, lane, run ID, sealed input hash, payload hash
- terminal status와 typed issue code
- eligible input count, published item/action count
- research attempted/succeeded/timed-out count와 source freshness bucket
- 기존 경로와의 후보/action 차이 및 아래 reason
- report basename과 RunJournal identity

원시 broker row, article body, provider error, local absolute path는 ledger에 복사하지 않습니다.

## 4. Classify every difference

| Reason | 사용 조건 | Gate 의미 |
| --- | --- | --- |
| `EXPECTED_POLICY_CHANGE` | manifest가 미리 허용한 compiler policy 차이 | 허용, 근거 rule ID 필수 |
| `INPUT_GAP` | sealed deterministic/broker input 차이 | 허용 가능, input identity diff 필수 |
| `SOURCE_GAP` | public source coverage/freshness 차이 | 허용 가능, typed issue 필수 |
| `BUG` | 구현 결함이 원인 | 실패, 수정 후 새 gate version/재검증 |
| `UNEXPLAINED` | 위 네 범주로 재현 불가 | 즉시 실패, 최종 0건 필수 |

기존 actionable 후보가 누락됐는데 reason과 source/input diff가 없으면 무조건
`UNEXPLAINED`입니다. `BLOCKED`나 `REVIEW`라는 결과만으로 설명이 되지는 않습니다.

## 5. Compute the graduation metrics

최소 20개의 **US 거래 session**을 모두 마친 뒤 계산합니다. 달력 20일이나 실행 20회로
대체하지 않습니다.

| Metric | 계산 | Pass |
| --- | --- | --- |
| session coverage | 관찰 완료 US session / manifest session | 20 sessions 이상, 모든 계획 slot 분류 |
| terminal coverage | terminal 또는 reconciled missed/stale slot / 계획 slot | 100%; missed/stale는 자동 pass가 아니라 원인 분류 필수 |
| unexplained diff | `UNEXPLAINED` count | 0 |
| privacy leak | sentinel scan failures | 0 |
| advice-only violation | order/notification capability access | 0 |
| deterministic replay | 같은 sealed input의 payload byte/hash mismatch | 0 |
| holding universe coverage | eligible SWING holding 중 compiler 미평가 수 | 0 |
| hard-SELL preservation | queue 밖 hard `SELL` 누락/강등 수 | 0 |
| invalid publication | schema/hash/key/identity invalid report 수 | 0 |
| existing-pipeline impact | 기존 result/exit/notification identity 변경 수 | 0 |

Provider failure-rate, research coverage, freshness는 lane과 provider별로 함께 보고합니다.
이 값은 manifest에 사전 threshold가 있을 때만 자동 pass/fail로 사용합니다. threshold가
없다면 graduation review의 정량 증거이지 사후에 만든 합격선이 아닙니다.

## 6. Run the final verification

```bash
just quality
just ci-web
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_decision_board_verification.py \
  tests/test_decision_board_privacy_integration.py \
  tests/test_decision_board_capability_contract.py -q
pnpm --dir web run test:e2e:decision-board
```

동일 sealed input replay를 별도로 실행해 canonical `decision_payload` bytes/hash가
byte-identical인지 확인합니다. research rerun의 source provenance 차이는 payload identity를
몰래 바꾸지 말고 별도 diff로 기록합니다.

## 7. Hold a manual graduation review

아래가 모두 준비됐을 때만 “다음 cutover 검토 자격 있음”으로 서명합니다.

- frozen manifest와 전체 session ledger
- 모든 diff의 reason, input/source diff, reviewer
- 위 hard metric 전부 pass
- provider/coverage/freshness 통계와 사전 threshold 결과
- privacy/no-order/workflow isolation 결과
- rollback rehearsal과 보존할 report/journal inventory
- 독립 reviewer의 Critical/Important 0건 판정

서명은 launchd를 load하거나 notification/주문 owner를 전환하지 않습니다. 활성화는 별도
one-way 운영 결정이며 schedule, credential scope, backup, rollback owner를 다시 승인해야
합니다. 주문 실행은 그 이후에도 사용자 수동입니다.

## Troubleshooting

### `CONFIG_UNAVAILABLE`, exit 2

정상 기본값입니다. production adapter가 승인·연결되지 않았으므로 측정 session으로 세지
마세요. 가짜 adapter로 실제 결과를 채우지 않습니다.

### `MISSED_EXPECTED` 또는 `STALE_INCOMPLETE`

record를 삭제하거나 terminal로 수동 변경하지 않습니다. manifest slot에 운영 실패로
기록하고 원인을 `INPUT_GAP`, `BUG`, `UNEXPLAINED` 중 재현 가능한 범주로 분류합니다.

### Optional upload failure

local artifact가 정확한지 먼저 확인합니다. local report가 보존됐으면 upload/index를
수리할 수 있지만 같은 identity의 object를 덮어쓰거나 삭제하지 않습니다.

### Policy/provider change during the period

현재 gate를 중단하고 새 gate version과 새 20-session 기간을 시작합니다. 서로 다른 policy
version의 결과를 하나의 합격 통계로 합치지 않습니다.

## Related

- [Decision Board V0 reference](decision-board.md)
- [Runbook](runbook.md)
- [Strategy](STRATEGY.md)
- [Architecture](ARCHITECTURE.md)
