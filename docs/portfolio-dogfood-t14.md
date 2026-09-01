# Portfolio dogfood T14

상태: Accepted (implemented and usable, synthetic local-only)

T14는 `/today`에서 Mandate, Evidence, Outcome의 public projection을 한 흐름으로
검토하는 fixture-only UI다. 실제 holding, provider, DB, order와 notification을 읽거나
쓰지 않는다.

## 사용자 흐름

`/today?dogfood=<scenario>#mandate-evidence-outcome`에서 다음 합성 상태를 선택한다.

- `corrected-lineage`: append-only event history의 최신 public correction projection
- `empty-outcome`: public outcome event가 없으며 어떤 상태도 추론하지 않음
- `blocked-evidence`: conflicting primary evidence 때문에 outcome projection을 보류함

선택은 native link의 URL query에만 존재하므로 keyboard로 이동할 수 있고 refresh 뒤에도
유지된다. unknown selection과 malformed query는 `INVALID SELECTION`, invalid fixture는
`FIXTURE CONTRACT INVALID`로 닫힌다.

## 개인정보와 비활성 경계

T14 fixture는 public instrument, approved synthetic mandate, public source span과 O1 public
outcome projection만 허용한다. 다음 실행 전용 필드는 schema와 UI에서 제외한다.

- account reference hash
- broker order/fill ID
- confirmed quantity와 price
- private feedback note

`provider_history_state`는 `NOT_EVALUATED`이며 실제 provider capability를 증명하지 않는다.
correction UI는 기존 O1 append-only 계약의 public projection을 표시할 뿐 event writer나
automatic match confirmation을 추가하지 않는다.

## 검증

```bash
pnpm --dir web exec vitest run \
  src/app/\(console\)/today/__tests__/page.test.tsx \
  src/components/__tests__/today-decision-board.test.tsx \
  src/components/__tests__/mandate-evidence-outcome-dogfood.test.tsx
pnpm --dir web run test:e2e:decision-board
pnpm --dir web run typecheck
pnpm --dir web run lint
pnpm --dir web run format:check
```

Playwright journey는 외부 origin과 Toss/order/notification/Supabase 문자열 요청을
차단하고 375, 768, 1280px에서 수평 오버플로, keyboard 선택, refresh retention,
correction/empty/blocked/invalid와 private-field 부재를 검증한다.
