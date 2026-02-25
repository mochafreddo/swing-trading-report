# Spec — Swing Trading Report v1.1 (Contracts)

상태: Draft (2026-02-25)  
목적: v1.1 기준 “운영에 필요한 계약(Contract)”을 한 문서에 고정합니다.  
범위: Supabase(저장/인덱스/런타임), 리포트 키 규칙, 웹 API가 의존하는 조회/업서트 규칙.

## 1. 비목표(Non-Goals)

- 전략 자체(신호/룰)는 `docs/STRATEGY.md`가 단일 소스입니다.
- 매수/매도 자동 주문은 범위 밖입니다.
- 본 문서는 UI 상세(컴포넌트 구조/스타일)를 정의하지 않습니다.

## 2. 용어

- **report**: Python 엔진(`sab scan`/`sab sell`)이 생성하는 JSON 산출물.
- **report_key**: Supabase Storage `reports` 버킷에 저장되는 오브젝트 키(=경로).
- **duplicate_index**: 같은 날짜/타입 리포트가 여러 번 생성될 때 충돌 회피용 인덱스(`-1`, `-2`, ...).
- **report_index**: 웹 목록/검색 성능을 위한 Postgres 인덱스 테이블.
- **runtime_state**: 로그인 시도 제한 등 “짧은 수명” 런타임 상태를 저장하는 테이블.

## 3. Storage Key 규칙 (Supabase Storage)

### 3.1 버킷

- 버킷: `reports` (private)

### 3.2 report_key 형식

- 키 규칙(필수): `YYYY/MM/YYYY-MM-DD(.n).{buy|sell}.json`
  - 예: `2026/02/2026-02-25.buy.json`
  - 예: `2026/02/2026-02-25-1.sell.json`
- `duplicate_index` 매핑 규칙
  - suffix가 없으면 `duplicate_index=0`
  - `-1`이면 `duplicate_index=1`

## 4. Postgres 계약 (Supabase)

### 4.1 Postgres: `holdings` (요약)

- 보유 종목 단일 소스(웹 CRUD 대상).
- 상세 스키마는 별도 문서/마이그레이션을 기준으로 합니다.

### 4.2 Postgres: 공통 운영 규칙

- RLS는 활성화 + 강제(force)이며, `anon/authenticated` 권한은 제거되어야 합니다.
- 서버(Admin) 키로만 접근합니다.

### 4.3 Postgres: `report_index` (필수)

목적: **리포트 목록/검색은 Storage를 직접 열거하지 않고 `report_index`를 기준으로 한다.**

#### 4.3.1 스키마 (요약/필수 필드)

- `report_key` TEXT PRIMARY KEY
- `report_type` TEXT NOT NULL (`buy`, `sell`만 허용)
- `report_date` DATE NOT NULL
- `duplicate_index` INTEGER NOT NULL DEFAULT 0 (`>= 0`)
- `tickers` TEXT[] NOT NULL DEFAULT `'{}'`
- `tickers_hydrated` BOOLEAN NOT NULL DEFAULT false
- `summary` JSONB NULL
- `generated_at` TEXT NULL (리포트 내부의 생성 시각 스냅샷)

#### 4.3.2 인덱스(필수)

- keyset pagination 최적화 인덱스(필수)
  - `report_index_type_date_duplicate_key_idx`
  - `report_index_date_duplicate_key_idx`

#### 4.3.3 Upsert 경로(필수)

- Python 파이프라인은 Storage 업로드 후, 다음 경로로 `report_index`를 upsert 해야 합니다.
  - `POST /rest/v1/report_index?on_conflict=report_key`

#### 4.3.4 조회 정렬(필수)

- 웹 목록 기본 정렬은 keyset-friendly order를 사용합니다.
  - `report_date.desc,duplicate_index.desc,report_key.desc`

#### 4.3.5 ticker 검색 계약(필수)

- ticker 검색(`q`)은 `tickers_hydrated=true` 행만 대상으로 한다.
  - `tickers_hydrated=false`는 “인덱스만 있고(혹은 파싱 실패) tickers가 비어있는 상태”로 간주하며,
    목록/검색 결과에서 제외하고 경고로 노출한다.

### 4.4 Postgres: `runtime_state` (필수)

목적: 로그인 시도 제한(throttle) 등 단기 상태를 저장한다.

#### 4.4.1 스키마 (필수 필드)

- `state_key` TEXT PRIMARY KEY
- `state_payload` JSONB NOT NULL
- `expires_at` TIMESTAMPTZ NOT NULL

#### 4.4.2 인덱스(필수)

- `runtime_state_expires_at_idx`
- `runtime_state_login_user_expires_at_idx`

#### 4.4.3 저장소 선택(필수)

- 런타임 상태 저장소는 다음 환경변수로 선택 가능해야 합니다.
  - `SAB_RUNTIME_STATE_STORE=memory|supabase`

#### 4.4.4 RPC(필수)

- 로그인 시도 제한은 DB 원자성을 위해 RPC를 사용합니다.
  - `POST /rest/v1/rpc/consume_login_throttle_attempt`

