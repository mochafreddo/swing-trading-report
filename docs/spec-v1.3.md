# Spec — Swing Trading Report v1.3 (Next)

상태: Draft (2026-02-25)  
목적: `docs/STRATEGY.md`의 개선 여지를 “다음 구현” 가능한 단위로 쪼개 **명확한 인터페이스/계약/수용 기준(acceptance)** 으로 정의합니다.

## 1. 배경/문제

현재 v1.2는 EOD(완성 일봉) 기반으로 후보(`scan`)와 보유 평가(`sell`)를 생성합니다.

실전 운용에서 반복되는 리스크는 아래 2가지입니다.

1. **신호일(EOD) ↔ 실행일(다음 거래일)** 간 괴리  
   - 다음날 시초 갭/초반 변동으로 인해 후보의 “진입 가능성”이 크게 바뀌지만, 현재는 이를 체계적으로 다루는 계약(`entry`)이 없습니다.
2. **리스크/품질 판단의 우선순위 불명확**  
   - corporate action 의심, 하드스탑, time stop 등 여러 신호가 동시에 발생할 때 “무엇이 무엇을 덮는지”가 계약으로 고정되어 있지 않아 운영자 해석 편차가 큽니다.

## 2. 목표 / 비목표

### 2.1 목표(Goals)

- `scan` 결과를 다음 거래일 “진입 관점”으로 다시 평가하는 `entry` 단계를 추가한다.
- 리포트 재현성을 위해, 실행 메타데이터를 일관된 스키마로 포함한다.
- (운영 안전) sell 규칙의 **우선순위/플래그**를 명확히 하여 “SELL이 REVIEW로 뒤집히는” 형태의 사고 가능성을 줄인다.

### 2.2 비목표(Non-Goals)

- 자동 주문/체결/포지션 사이징(수량 결정).
- 분봉/멀티타임프레임 기반의 정교한 entry 모델(예: opening range breakout).
- 백테스트 프레임워크 구축.

## 3. 범위 요약(Deliverables)

- D1. `sab entry` 서브커맨드 추가(“다음 거래일 진입 판단 보조” 리포트 생성)
- D2. buy candidate 공통 필드 확장(갭/가드/핵심 지표의 numeric 값 포함)
- D3. ema_cross 점수/노트의 “옵션 필터” 의미 정합성 수정(스코어 계약 고정)
- D4. sell: corporate action 의심은 **action을 덮지 않고 flag로 승격**(우선순위 계약)
- D5. sell: time stop의 단위를 명시(거래일 세션 기준 권장) + 리포트에 계산값 노출
- D6. 리포트 메타데이터(재현성) 표준 필드 추가

## 4. 인터페이스 스펙

### 4.1 CLI: `sab entry`

#### 4.1.1 목적

- 전일(또는 직전) `buy` 리포트를 입력으로 받아, **현재 세션** 가격 스냅샷 기준으로 “진입 관점”의 액션을 산출합니다.

#### 4.1.2 명령/옵션 (초안)

- `uv run python -m sab entry`
  - `--buy-report` (optional): 입력 buy JSON 경로. 미지정 시 `reports/`에서 최신 buy를 자동 선택.
  - `--provider` (optional): `kis|pykrx`. entry는 실시간/당일 가격이 필요하므로 기본 `kis`를 권장(단, 구현 가능성에 따라 pykrx는 “EOD 이후” 모드로 제한).
  - `--mode` (optional): `PRE_OPEN|INTRADAY` (기본 `PRE_OPEN`)
  - `--upload` (optional): Storage 업로드/인덱싱 수행 여부(기본: v1.1 정책과 동일)

#### 4.1.3 출력 아티팩트

- 로컬: `reports/YYYY-MM-DD(.n).entry.json`
- (선택) Supabase Storage: `YYYY/MM/YYYY-MM-DD(.n).entry.json`

> **DB/웹 UI 연동 여부**
> - v1.3에서 entry 리포트를 웹에서 조회하려면 `report_index.report_type` 허용값에 `entry`를 추가해야 합니다(5.3 참고).
> - “우선 로컬 파일만 생성”으로 MVP를 먼저 내고, 후속으로 Storage/Index/UI를 붙이는 단계적 구현도 허용합니다.

### 4.2 Entry 리포트 JSON 스키마(초안)

- 최상위 필드(필수)
  - `schema_version`: `"entry-v1"`
  - `report_type`: `"entry"`
  - `generated_at`: ISO8601 string
  - `source_buy_report`: 입력 buy 리포트의 파일명 또는 storage key
  - `signal_eval_date`: buy 리포트의 평가 캔들 날짜(=신호일)
  - `entry_session_date`: entry 실행 세션 날짜(=실행일)
  - `entries`: 배열
  - `system_issues`: 배열(가격 조회 실패, 데이터 부족 등)

- `entries[]` 필드(필수)
  - `ticker`
  - `action`: `ENTER|REVIEW|SKIP`
  - `reasons`: string[]
  - `signal_close` (numeric): 신호일 종가(또는 eval candle close)
  - `entry_price` (numeric): entry 시점 관측 가격(모드별 정의)
  - `gap_pct` (numeric)
  - `gap_guard_pct` (numeric|null)
  - `gap_guard_up_price` / `gap_guard_down_price` (numeric|null)
  - `strategy_mode` + (선택) `pattern` / `entry_state` (hybrid의 경우)

## 5. 룰/계약(Decision Rules)

### 5.1 Entry 액션 결정 (MVP)

Entry는 “진입 가능성”을 세 단계로 분류합니다.

- `ENTER`: 계획된 진입 조건을 만족(갭/확인 신호 충족).
- `REVIEW`: 진입 자체는 가능하나 리스크/불확실성이 커서 수동 확인이 필요.
- `SKIP`: 갭/확장/데이터 실패 등으로 오늘은 진입을 스킵하는 것이 기본.

#### 5.1.1 기본 우선순위

1) **시스템 이슈(가격 조회 실패/데이터 불충분)** → `REVIEW`(보수적)  
2) **갭 가드 초과** → `SKIP`(기본) 또는 설정에 따라 `REVIEW`  
3) 전략별 확인 조건 → `ENTER|REVIEW`

#### 5.1.2 갭 계산/가드

- `gap_pct = (entry_price - signal_close) / signal_close`
- `gap_guard_pct`는 ATR 기반 가드로 산출하며, v1.3에서는 buy report에 모든 candidate가 이를 포함하도록 표준화합니다(6.1).
- 기본 정책(초안):
  - `abs(gap_pct) <= gap_guard_pct` → 통과
  - `abs(gap_pct) > gap_guard_pct` → `SKIP` + reason에 guard 초과 기록

### 5.2 ema_cross score 계약 정합성(필수)

현재 ema_cross 평가에서 “옵션 필터를 켜지 않았는데도 점수에 포함”되는 형태는 운영 해석을 흐립니다.

v1.3 계약:

- `use_sma200_filter=false`이면 `sma200` 점수 항목은 **N/A**로 취급하며, `score_notes`에 포함하지 않는다.
- `require_slope_up=false`이면 `slope` 점수 항목은 **N/A**로 취급하며, `score_notes`에 포함하지 않는다.
- 반대로 옵션이 켜져 있을 때만 `pass/fail`이 점수/노트에 반영된다.

### 5.3 Supabase `report_index`에 entry를 넣을 경우(확장)

v1.3에서 entry 리포트를 Storage/웹에 올릴 경우 아래 변경이 필요합니다.

- `report_index.report_type` 허용값 확장: `buy|sell|entry`
- Storage key 정규식/파서 확장: `.entry.json`을 허용
- key 생성기 확장: `build_report_storage_key(run_type="entry")` 지원

> 이 변경은 DB check constraint 및 Python/web 경로 모두에 영향을 줍니다. 구현 시점에 `docs/spec-v1.3.md`를 “정답”으로 두고, `docs/spec-v1.1.md` 및 테스트를 함께 갱신합니다.

### 5.4 Sell: corporate action 의심 우선순위(필수)

v1.3 계약:

- corporate action 의심은 **action을 덮어쓰지 않는다.**
  - 예: 하드 스탑/커스텀 스탑으로 `SELL`인 경우, corporate action 의심이 있어도 `SELL`은 유지한다.
- 대신 별도 필드로 “플래그”를 올린다.
  - 제안: `flags: ["CORPORATE_ACTION_SUSPECT"]`
- UI/운영에서는 “수량/단가 조정 여부 확인 후 실행”을 안내한다.

### 5.5 Sell: time stop 단위(필수)

v1.3 계약(권장):

- `time_stop_days`는 **calendar day가 아니라 trading sessions** 기준으로 해석한다.
- sell 리포트에는 아래 값을 노출한다.
  - `days_in_trade_sessions` (int)
  - `time_stop_triggered` (bool)

> 구현은 KR/US 각각의 trading calendar(내장 + override JSON) 기반으로 “entry_date → eval_date 사이의 장 개장일 수”를 계산합니다.

## 6. 데이터/스키마 변경(Report-level)

### 6.1 buy candidate 공통 필드 확장(필수)

Entry 및 운영 안정성을 위해, buy report의 후보(candidate)는 최소한 아래 numeric 필드를 공통 제공해야 합니다.

- `close_value`(=eval candle close; 기존 `price_value`와 의미가 같다면 명확히 정리)
- `atr14_value` (float)
- `gap_guard_pct_value` (float|null)
- `gap_guard_up_price_value` / `gap_guard_down_price_value` (float|null)

> v1.3에서는 “표시용 문자열”과 “계산용 numeric”를 분리해 계약을 고정합니다.

### 6.2 리포트 메타데이터 표준(필수)

buy/sell/entry 공통으로 아래 메타를 포함합니다.

- `generated_at` (기존 유지)
- `run_id` (UUID 추천)
- `run_ts_utc` (ISO8601)
- `git_sha` (가능하면; 로컬은 optional)
- `eval_context`:
  - `market`(KR/US), `session_state`(PRE_OPEN/INTRADAY/AFTER_CLOSE), `eval_index_policy` 등
- `config_snapshot`(선택): 핵심 파라미터만 축약해 포함(민감정보 제외)

## 7. 수용 기준(Acceptance Criteria)

- `sab entry`는 최소 1개 buy 리포트를 입력으로 받아, `entries[]`를 가진 entry JSON을 생성한다.
- entry JSON은 각 엔트리에 대해 `gap_pct` 및 갭 가드 관련 필드가 채워져야 한다(가드 산출 불가 시 null + reason).
- ema_cross score/notes는 옵션 필터가 비활성일 때 해당 항목을 포함하지 않는다.
- sell 평가에서 corporate action 의심이 발생해도 기존 `SELL` 액션은 `REVIEW`로 다운그레이드되지 않는다(플래그로 표현).
- time stop은 “세션 기준” 계산값이 리포트에 노출되며, 주말/휴일이 결과에 일관되게 반영된다.

## 8. 테스트 계획(요약)

- 단위 테스트
  - entry: 갭 가드 통과/초과 케이스(ENTER/REVIEW/SKIP) 결정 규칙.
  - ema_cross: score_notes에 N/A 항목이 포함되지 않는지.
  - sell: corporate action 플래그가 `SELL`을 덮지 않는지.
  - time stop: 세션 수 계산(주말/휴일/미국 조기마감은 “휴일 여부”만 반영, 조기마감은 세션 수 동일 처리).
- 통합 테스트(선택)
  - Storage 업로드/`report_index` upsert (entry를 포함할 경우).
