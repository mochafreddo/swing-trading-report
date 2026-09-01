# Portfolio Outcome T15 adapter seam

상태: Implemented and usable (recorded/redacted local-only)

T15는 실제 broker 주문 이력 provider를 연결하기 전에 pagination과 privacy 계약을
실행 가능하게 고정하는 입력 adapter seam이다. O1 matcher와 correction event 계약은
그대로 재사용하며 provider, DB, writer, order와 notification capability를 추가하지
않는다.

## 입력 모드

- `RECORDED`: 저장소의 합성 recorded page fixture를 검증한다.
- `REDACTED_IMPORT`: 최대 1 MiB local bytes를 strict UTF-8, duplicate-key-aware JSON으로
  읽는다.

두 모드 모두 `provider_history_state=NOT_EVALUATED`를 강제한다. 이는 실제 provider
보존 기간, read-only scope 또는 pagination 동작을 확인했다는 뜻이 아니다.

## Pagination과 lineage

첫 page의 `request_cursor`는 null이고, 각 다음 page의 request cursor는 직전
`next_cursor`와 정확히 같아야 한다. 마지막 `next_cursor`가 null일 때만
`pagination_state=COMPLETE` 결과를 만든다. 불연속, 반복 cursor와 incomplete tail은
execution lineage를 O1에 전달하기 전에 차단한다.

완전한 page chain은 기존 O1 execution validator로 다시 검증한다. 따라서 cancel/reorder
direct chain, positive fixed-six price/quantity, exact slice/candidate target, lineage ID와
`(broker_order_id, broker_fill_id, account_ref_hash)` 중복 금지가 page 경계를 넘어
유지된다.

## Redacted import privacy

account reference는 `hmac-sha256:v1:<64 lowercase hex>`만 허용한다. raw account,
unknown field, malformed broker ID, invalid UTF-8, duplicate JSON key와 byte cap 초과는
fail closed한다. 이 입력은 local memory에서만 adapter 결과로 변환되며 persistence나
upload를 수행하지 않는다.

## 검증

```bash
UV_CACHE_DIR=.uv-cache uv run pytest -q \
  tests/test_portfolio_outcome_history_t15.py \
  tests/test_portfolio_outcome_contracts.py
UV_CACHE_DIR=.uv-cache uv run ruff check \
  sab/portfolio_mandate/outcome_history.py \
  sab/portfolio_mandate/outcomes.py \
  tests/test_portfolio_outcome_history_t15.py
UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml \
  sab/portfolio_mandate/outcome_history.py \
  sab/portfolio_mandate/outcomes.py \
  tests/test_portfolio_outcome_history_t15.py
```

테스트는 complete two-page replay, incomplete/discontinuous pagination, cross-page duplicate
fill, bounded redacted import와 adapted lineage를 사용한 append-only correction replay를
검증한다.
