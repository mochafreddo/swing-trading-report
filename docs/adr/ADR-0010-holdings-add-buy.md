## ADR-0010 — Holdings 추가매수(Add Buy) 입력: Supabase RPC 원자 업데이트 + 평단 자동 재계산

상태: 채택(Accepted)  •  날짜: 2026-03-03

### 배경

- `holdings`는 보유 종목의 단일 소스이며(`web` CRUD → Supabase Postgres), `sell` 워크플로우는 DB에서 holdings를 읽어 `holdings.generated.yaml`로 브리지한 뒤 `sab sell`에 주입합니다.
- 현재 추가매수(평단/수량 변경)는 사용자가 `quantity`, `entry_price`, `entry_date`를 수동으로 재계산/수정해야 합니다.
- 이 과정은 입력 실수가 잦고(가중평균 오산/오타), 특히 US 종목에서 `entry_currency` 누락/불일치가 발생하면 `sab/holdings_loader.py`의 fail-closed 규칙으로 `sell` 실행이 실패할 수 있습니다.

### 결정

Holdings에 “추가매수(Add Buy)” 입력을 도입하며, 다음 정책을 채택합니다.

1. **Supabase RPC로 원자적 업데이트(권장안 채택)**
  - 계산(평단/수량)과 검증(통화/정밀도/전제조건)을 DB 트랜잭션 내부에서 수행합니다.
  - 동시 요청/더블클릭 등으로 인한 경합에서 “읽기-계산-PATCH” 레이스를 피합니다.

2. **평단 계산 규칙(가중평균)**
  - `new_qty = old_qty + buy_qty`
  - `new_entry_price = (old_qty*old_entry_price + buy_qty*buy_price) / new_qty`
  - 저장 정밀도는 DB 스키마에 맞춰 `quantity=round(,6)`, `entry_price=round(,4)`로 고정합니다.

3. **entry_date 업데이트 규칙(권장안 채택)**
  - `buy_date`가 주어지면 `entry_date = MIN(existing_entry_date, buy_date)`를 적용합니다.
  - `buy_date`가 없으면 `entry_date`는 변경하지 않습니다.
  - 의도: `sab sell`의 time stop/ATR trail anchor 의미(“최초 진입일”)를 보수적으로 유지합니다.

4. **통화 정책(안전성 우선)**
  - ticker로 시장을 판별해 required currency를 강제합니다.
    - KR(6-digit) → `KRW`
    - US(suffix) → `USD`
  - 기존 `entry_currency`가 `NULL`이면 required currency로 자동 채웁니다.
  - 기존 `entry_currency`가 required와 불일치하면 즉시 실패합니다(조용한 교정 금지).

5. **전제조건(침묵형 데이터 손상 방지)**
  - `old_qty > 0`인데 `old_entry_price <= 0`이면 추가매수로 평단을 재계산할 수 없으므로 실패합니다.
  - `old_qty = 0`(비활성 holding)인 경우에는 `entry_price`가 0이어도 허용하며, 추가매수는 “새 진입”처럼 처리됩니다(평단=buy_price).

6. **이벤트 로그/Undo는 MVP 범위 밖**
  - Phase 2에서 `holding_events`(또는 유사) 이벤트 테이블로 확장합니다.
  - MVP의 Add Buy는 holdings row의 수치만 갱신하며, notes 자동 append는 하지 않습니다(길이/드리프트/편집 UX 리스크).

7. **요청 멱등성**
  - API는 UUID 형식 `Idempotency-Key`를 필수로 받아 동일 키 재요청 시 기존 결과를 반환합니다.
  - 동일 키에 서로 다른 payload가 들어오면 `409` 충돌로 차단합니다.
  - DB 이벤트 테이블(`holdings_add_buy_events`)은 `request_fingerprint`를 저장하고, 처리 완료 이벤트 및 장기 미처리 이벤트는 별도 cleanup 스케줄 작업으로 90일 보존 후 배치 정리합니다.

### 결과/영향

- 장점
  - 사용자 입력은 “추가수량/추가단가/날짜”로 축소되고, 평단/수량 산출 실수를 크게 줄입니다.
  - DB 원자성으로 레이스/정밀도 문제를 최소화합니다.
  - 통화 정책을 강제해 `sell` 파이프라인의 fail-closed 실패 확률을 낮춥니다.
- 단점
  - Supabase migration/RPC 추가가 필요합니다.
  - 이벤트 로그가 없으므로 실수 시 “되돌리기”는 수동 보정(Phase 2에서 해소)입니다.

### 대안 검토

- 서버(Next.js)에서 계산 후 PATCH:
  - 구현은 빠르지만 원자성이 약하고(레이스), 반올림/정밀도 정책이 경로마다 흔들릴 수 있어 배제합니다.
- holdings에 복수 랏(트레이드 저널) 모델 도입:
  - 정확하지만 범위가 커지고(sell 평가/표시/이관), 현재 시스템 목표(리포트 기반 의사결정 지원)에 비해 과합니다.
