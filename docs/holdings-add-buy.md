# Holdings 추가매수 입력 설계 (Web Console)

상태: Draft (2026-03-03)  
대상: `web`의 Holdings CRUD + Supabase `public.holdings` (단일 사용자)  
관련: `docs/holdings-schema.md`, `docs/ARCHITECTURE.md` (Holdings CRUD), `.github/workflows/sell.yml` (holdings → sell 입력 브리지)

## 0) 결정(확정)

본 문서의 권장안은 다음 ADR로 확정합니다.

- ADR: `docs/adr/ADR-0010-holdings-add-buy.md`
  - 구현은 **Supabase RPC(원자 업데이트)** 를 채택합니다.
  - `entry_date`는 `MIN(existing, buy_date)` 정책을 채택합니다.
  - ticker 기반 통화 정책(KR=KRW, US=USD) 자동 채움/불일치 fail-closed를 채택합니다.
  - 수수료/환전/세금 등 원가 요소는 MVP 범위에서 제외합니다.

## 1) 문제

현재 “보유 종목에 추가매수”를 반영하려면 사용자가 직접 다음 값을 재계산/수정해야 합니다.

- `quantity` 증가
- `entry_price`(평단) 재계산
- (선택) `entry_date` 보정

이 흐름은 입력 실수(평단/수량) 가능성이 높고, 특히 US 종목에서 `entry_currency=USD` 누락/오입력 시 `sab sell` 경로(holdings.generated.yaml 로드)가 fail-closed로 깨질 수 있습니다.

## 2) 목표 / 비목표

### 목표

- (G1) 기존 holding에 “추가매수(Add Buy)”를 **별도 입력 폼**으로 제공한다.
- (G2) 추가매수 입력만으로 `quantity`, `entry_price`를 **자동 산출**하고 DB에 반영한다.
- (G3) 저장 전에 “반영 후 값(미리보기)”을 보여 사용자 실수를 줄인다.
- (G4) US/KR 시장에 따른 `entry_currency` 누락/불일치 입력을 **fail-closed**로 막는다(또는 안전한 자동 채움).

### 비목표(초기)

- 증권사 연동/자동 체결.
- 전체 트레이드 저널(복수 랏, FIFO/LIFO, 실현손익).
- 부분매도 입력 UX(추후 “수량 감소/매도 기록”으로 별도 기획).

## 3) UX 설계

### 3.1 Holdings 테이블: Row Action 추가

- 기존: `Edit`, `Delete`
- 추가: `Add Buy`

`Add Buy` 클릭 시 해당 ticker에 대한 추가매수 패널(또는 모달)을 연다.

결정(권장 UX, MVP):

- 모달 대신 기존 좌측(또는 상단) `aside` 패널을 “Add Buy 모드”로 전환한다.
- 이유: 입력 집중 + 구현 단순성(페이지 구조 추가 최소화).

### 3.2 Add Buy 패널(제안 UI 필드)

- Readonly 요약(현재값)
  - `ticker`
  - `current_quantity`
  - `current_entry_price`
  - `current_entry_currency`(없으면 “미설정” 표시)
  - `current_entry_date`(없으면 “미설정” 표시)
- 입력(사용자)
  - `buy_quantity` (필수, `> 0`)
  - `buy_price` (필수, `> 0`)
  - `buy_date` (선택, 기본값: 오늘)
  - `note`는 MVP에서 받지 않는다(이벤트 로그/Undo 도입 시 함께 추가).

### 3.3 반영 미리보기(저장 전 계산 결과)

입력값이 유효하면 아래를 즉시 계산해 표시한다.

- `next_quantity`
- `next_entry_price` (가중평균 평단)
- `next_entry_date` (정책에 따라 변경 여부/값 표시)
- `next_entry_currency` (정책에 따라 자동 채움/검증 결과 표시)

### 3.4 저장 후 동작

- 성공: holding row가 갱신되고(= `updated_at` 갱신), 테이블이 refresh된다.
- 실패: 원인을 폼 상단에 표시한다(HTTP status + 메시지).

## 4) 계산/검증 규칙(Contract)

### 4.1 가중평균 평단

- 입력:
  - `old_qty`, `old_price`
  - `buy_qty`, `buy_price`
- 출력:
  - `new_qty = old_qty + buy_qty`
  - `new_price = (old_price * old_qty + buy_price * buy_qty) / new_qty`

제약:

- `buy_qty > 0`, `buy_price > 0`
- `old_qty >= 0`, `old_price >= 0`(기존 스키마 계약)
- `new_qty > 0`

추가 전제조건(침묵형 데이터 손상 방지, 확정):

- `old_qty > 0`인데 `old_price <= 0`이면 평단 재계산이 불가능하므로 요청을 실패 처리합니다.
- `old_qty = 0`(비활성 holding)인 경우에는 “새 진입”처럼 처리되어 `new_price = buy_price`가 됩니다.

### 4.2 반올림/정밀도

Supabase 스키마(현재):

- `quantity`: `numeric(20, 6)`
- `entry_price`: `numeric(20, 4)`

따라서 저장 전/후 값의 drift를 줄이기 위해 다음을 권장합니다.

- `new_qty`는 소수 6자리로 `round(..., 6)`
- `new_price`는 소수 4자리로 `round(..., 4)`

### 4.3 entry_date 업데이트 정책(초기 권장)

정책: `MIN(existing, buy_date)` (보수적으로 “포지션 최초 진입일”을 유지)

- `buy_date`가 제공되지 않으면 `entry_date`는 변경하지 않는다.
- `entry_date`가 비어 있고 `buy_date`가 있으면 `entry_date = buy_date`.

> 주의: `sab sell`의 time stop / ATR trail anchor가 `entry_date`에 의존합니다.  
> 정책을 `RESET`(마지막 추가매수일로 리셋)로 바꾸면 평가 결과가 달라지므로, 변경 시 별도 ADR/STRATEGY 업데이트가 필요합니다.

### 4.4 entry_currency 정책(초기 권장)

목표: `sab sell`(holdings YAML 로더) fail-closed 규칙과 충돌하지 않도록, “시장에 맞는 통화”를 강제한다.

- 시장 판별:
  - KR ticker(6-digit): required currency = `KRW`
  - US ticker(with exchange suffix): required currency = `USD`
- 동작:
  - holding의 `entry_currency`가 `null`이면 required currency로 **자동 설정**한다(추가매수 저장과 함께).
  - holding의 `entry_currency`가 required와 다르면 **즉시 실패**(409 또는 400).

> 기존 holdings create/edit에서도 동일 규칙을 적용하는 것이 이상적이지만, 초기 범위는 Add Buy에만 적용해도 운영 사고를 크게 줄일 수 있습니다.

추가 권장(Phase 1.1):

- holdings create/edit에서도 ticker 기반으로 `entry_currency`를 자동 채움/검증한다.
- 가능하면 DB 레벨 check constraint로도 고정해 “UI/스크립트 우회”를 막는다.

## 5) API 설계 (Web)

### 5.1 Endpoint

제안:

- `POST /api/holdings/{ticker}/add-buy`

Auth/guard:

- 기존 holdings CRUD와 동일: `requireAdminAuth` + `same-origin` + `local-request`
- `Idempotency-Key` 헤더 필수: UUID 형식만 허용, 동일 키 재시도는 기존 결과를 반환(중복 반영 방지)

### 5.2 Request/Response (예시)

Request:

```json
{
  "buy_quantity": 3,
  "buy_price": 102.55,
  "buy_date": "2026-03-03"
}
```

Response: 기존 `HoldingRecord`(갱신된 row) 반환.

Header:

- `Idempotency-Key: <uuid>`
- 최대 길이: 128자

### 5.3 Error 정책(권장)

- `400`: payload 검증 실패(음수/0, 날짜 포맷, ticker invalid), `Idempotency-Key` 누락/형식 오류
- `404`: holding 없음
- `409`: 통화 불일치, 동일 `Idempotency-Key`의 payload 불일치, 동시성 충돌(옵션), 또는 정책 위반  
  - payload 불일치 응답은 `code=IDEMPOTENCY_KEY_PAYLOAD_MISMATCH`를 함께 반환(클라이언트 자동 키 재발급 트리거용)
- `500`: 알 수 없는 서버 오류

## 6) 구현 옵션(권장안 포함)

### 옵션 A) Next.js에서 fetch → 계산 → PATCH

- 장점: DB migration 없이 빠르게 구현.
- 단점: 완전 원자적이지 않음(더블클릭/동시 요청에서 드물게 drift 가능).

### 옵션 B) Supabase RPC로 원자적 업데이트 (권장, 채택)

Supabase에 RPC 함수를 추가해 **단일 트랜잭션**으로 처리한다.

- 장점:
  - 원자성/정밀도(ROUND) 강제
  - 통화 정책/티커 정규화 정책을 DB 레벨에 고정 가능
  - Web 서버 코드는 “입력 검증 + RPC 호출 + 결과 반환”으로 단순화
- 단점: migration이 필요

RPC 시그니처 예:

- `public.holdings_add_buy_v1(p_ticker text, p_buy_quantity numeric, p_buy_price numeric, p_buy_date date default null, p_idempotency_key text default null)`
- 반환: `public.holdings` row (업데이트 후)

멱등 이벤트 로그:

- `holdings_add_buy_events` 테이블에 `(canonical_ticker, idempotency_key)` PK + `request_fingerprint`를 저장합니다.
- 동일 키 재요청 시 fingerprint가 같으면 기존 결과를 반환하고, 다르면 `409` 충돌로 차단합니다.
- `processed=true` + `created_at` 90일 초과 이벤트와 `processed=false` + `updated_at` 90일 초과 이벤트를 `cleanup_holdings_add_buy_events()`로 배치 정리합니다.
- 스케줄 작업(`holdings-add-buy-events-cleanup`, `30 3 * * *`)은 `public.cleanup_holdings_add_buy_events(interval '90 days', 500)`를 호출합니다.
- `pg_cron`이 비활성인 환경에서는 스케줄 보강 마이그레이션이 실패하도록 하여(무음 skip 금지) 운영자가 확장 활성화를 명시적으로 수행하게 합니다.
- 운영 점검 SQL(등록/수동 실행/실행 이력)은 `docs/runbook.md`의 “보유 목록(holdings)” 섹션을 기준으로 사용합니다.

라우팅/티커 별칭 정책:

- DB에는 class ticker가 `BRK/B.NYS` 형태로 저장될 수 있으므로, RPC는 `canonical_holdings_ticker()` 기준으로 row를 찾아야 한다.
  - 예: 입력 `BRK.B.NYS` → canonical 비교로 `BRK/B.NYS` row를 업데이트


## 7) (선택) 이벤트 로그/되돌리기(Phase 2)

추가매수는 “수치가 바뀌는” 입력이므로 실수 대응을 위해 이벤트 로그가 유용합니다.

### 7.1 테이블 제안: `holding_events`

- `id` uuid pk
- `ticker` text (FK는 강제하지 않아도 됨; canonical unique 정책은 유지)
- `event_type` text (`BUY_ADD`, `MANUAL_EDIT`, `SELL_REDUCE` 등)
- `quantity` numeric(20,6) (delta 또는 abs 정책 중 택1)
- `price` numeric(20,4) null
- `event_date` date null
- `meta` jsonb null (UI 버전, request id 등)
- `created_at` timestamptz default now()

### 7.2 UX 확장

- holding row 클릭 시 “최근 변경/추가매수 내역” 패널 노출
- 마지막 이벤트 1건 “Undo” (가능하면) 제공

## 8) 테스트/검증(구현 단계)

- 계산 규칙 유닛 테스트
  - 가중평균(정수/소수, old_qty=0)
  - ROUND 정책(6/4 자리)
  - entry_date 정책(min/null)
  - 통화 정책(US=USD, KR=KRW)
- API route 테스트
  - auth/guard
  - 400/404/409 케이스
  - 성공 시 holding row가 갱신되어 반환됨
- (RPC 채택 시) RPC 결과 파싱/에러 처리 테스트

## 9) 단계적 롤아웃(제안)

1. Phase 1 (MVP): `Add Buy` UX + API(+ RPC 또는 서버 계산) + 미리보기
2. Phase 1.1: holdings create/edit에도 currency 정책 적용(자동 채움/검증)
3. Phase 2: `holding_events` 이벤트 로그 + UI 표시 + (선택) Undo
4. Phase 3: holdings.yaml import/export에 이벤트(복수 랏) 모델 확장(버전 bump)

## 10) 오픈 질문(결정 필요)

- Q1. `entry_date` 정책: `MIN(existing, buy_date)`로 고정(확정).
- Q2. 구현 경로: Supabase RPC로 바로 진행(확정).
- Q3. 수수료/환전/세금: MVP 범위에서 제외(확정).
