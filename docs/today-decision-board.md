# Today 의사결정 보드와 미분류 로컬 미리보기

상태: Accepted (local advice-only projection, memory-only private preview)

`/today`는 최신 ENTRY/HOLDING Decision Board 공개 projection과 local RunJournal
주의 상태를 한 화면에 모은다. 루트 `/`도 `/today`로 이동한다. 모든 매수·매도는
사용자가 직접 수행하며 이 화면에는 주문, 승인, 저장 또는 알림 capability가 없다.

## 공개 projection 경계

서버 페이지는 관리자 인증을 먼저 확인한 뒤 ENTRY/HOLDING latest index, 검증된
상세 report와 local journal 상태를 병렬로 읽는다. malformed index/report, lane
identity 불일치 또는 journal reader 실패는 raw payload나 경로를 노출하지 않고 해당
lane warning 또는 별도 journal warning 상태로 닫힌다.

Decision Board V0 report는 `valid_until`과 현재 dependency freshness를 증명하지
않으므로 PUBLISHED item도 active advice로 승격하지 않는다. source action은
`FRESHNESS_UNPROVEN · NOT ACTIVE`인 역사적 감사 사실로만 표시한다. 상단 action
count와 active queue에는 freshness가 증명된 item만 포함하며, 현재 계약에서는 항상
0이다. report나 journal이 없다는 사실로 절대적인 `NO ACTION`을 추론하지 않는다.

## Unclassified Queue 입력 계약

Unclassified Queue는 서버 경로가 아닌 client component다. 선택한 파일을
`File.text()`와 `JSON.parse()`로 현재 브라우저 tab 메모리에서만 읽고 strict Zod
contract로 전체 문서를 원자적으로 검증한다. 다음 조건을 모두 만족해야 preview를
표시한다.

- schema version이 `portfolio-mandate-a2-private-input.v0`이다.
- state가 정확히 `USER_INPUT_RECORDED_UNCLASSIFIED`다.
- snapshot은 Toss holdings read source, 관측 시각, USD ranking contract와 private
  field 미포함 flag 두 개의 `false`를 보존한다.
- holdings는 정확히 5개이고 모든 row가 `UNCLASSIFIED`, null horizon, 일관된
  thesis/invalidation recall 상태를 가진다.
- ticker와 모든 field가 strict contract에 맞고 unknown/private field가 없다.
- 파일 크기가 1,000,000 bytes 이하다.

검증 실패 시 이전 preview까지 제거하고 부분 row를 남기지 않는다. 사용자가 파일을
빠르게 다시 선택하거나 읽는 중 Clear를 눌러도 이전 비동기 읽기 결과는 무효화한다.

## 표시와 개인정보

성공한 preview는 다음 정보만 표시한다.

- snapshot 관측 시각과 `holding_count`
- top-5 ticker
- `UNCLASSIFIED · NO ADVICE`
- nullable `proposed_horizon`을 `UNAPPROVED DRAFT`로 표시한 값
- horizon, thesis와 invalidation을 사용자가 확인하기 위한 작업 문구

thesis와 invalidation의 private 본문은 화면에 표시하지 않는다. preview는 fetch,
API route, form submit, Supabase, provider, `localStorage`, `sessionStorage` 또는
IndexedDB를 사용하지 않는다. 새로고침이나 Clear는 현재 tab의 preview를 제거한다.

파일이 업로드되지 않더라도 ticker와 proposed horizon은 화면 DOM에 렌더링된다.
실제 private 파일을 연 상태의 스크린샷, 화면 공유와 브라우저 개발자 도구 출력은
private 정보로 취급한다.

## 사용 순서

1. 로컬 관리자 인증 뒤 `/today`를 연다.
2. `Unclassified queue JSON`에서 strict A2 private input 파일을 선택한다.
3. 관측 시각, top-5 subset 범위와 각 row의 확인 작업만 검토한다.
4. 검토가 끝나면 `Clear local preview`를 누르거나 tab을 새로고침한다.

화면의 draft는 mandate 승인 event가 아니며 DB나 journal을 변경하지 않는다. 실제
분류 승인과 activation은 별도 user-authorized writer가 구현되고 승인되기 전까지
비활성이다.

## 검증

다음 명령이 strict schema, privacy 경계, 읽기 경쟁, 대용량 거부, action count 불변과
production build를 검증한다.

```bash
pnpm --dir web exec vitest run \
  src/lib/__tests__/portfolio-mandate-a2-private-input-schema.test.ts \
  src/components/__tests__/unclassified-queue-preview.test.tsx \
  src/components/__tests__/today-decision-board.test.tsx
just ci-web
```

실제 private 값 대신
`tests/fixtures/portfolio_mandate/portfolio-mandate-a2-unclassified-preview.synthetic.json`
만 자동 테스트와 브라우저 QA에 사용한다.

## 관련 문서

- [Portfolio Mandate A1 비활성 계약](portfolio-mandate-a1-contract.md)
- [Portfolio Outcome O1 합성 계약](portfolio-outcome-o1-contract.md)
- [Decision Board V0 reference](decision-board.md)
- [Architecture](ARCHITECTURE.md)
