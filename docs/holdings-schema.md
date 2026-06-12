# holdings.yaml Schema

상태: Accepted (참조 문서)

이 문서는 `holdings.yaml` 파일 구조를 정의합니다.

- 권장: 보유 목록은 Supabase(Postgres)에서 관리하고, `holdings.yaml`은 import/export 용도로 사용합니다.
- 단, 초기에는 `holdings.yaml`만으로도 Sell/Review 평가가 가능합니다(자동 실행은 DB가 더 안전).

## 문서 상태

### 현재 제공

- 보유 목록의 단일 운영 소스는 Supabase `holdings`이며, `holdings.yaml`은 백업/import-export 입력으로 지원합니다.
- YAML import는 dry-run + replace-all semantics, export는 전체 snapshot(`quantity=0` 포함) 기준으로 동작합니다.
- 통화/티커 fail-closed 계약은 앱과 CLI 로더 양쪽에서 강제됩니다.
- 로컬 Python 로더는 선택적 `entry_pattern`을 받아 sell 평가에 전달합니다. Supabase는 Phase A에서 nullable 컬럼/RPC 계약만 준비했고, 웹과 scheduled export가 필드를 소유하기 전까지 non-null DB write는 닫아둡니다.

### 실험

- 별도 실험 스키마 버전은 현재 운영 기준에 포함하지 않습니다.

### 백로그

- `settings` 블록 확장과 복수 랏/이벤트 모델 연동은 backlog로 남아 있습니다.

### 폐기 후보

- `holdings.yaml`을 다시 주 저장소로 되돌리는 방향은 채택하지 않습니다.

## 관리 방식(권장)

- 보유 목록은 **웹 UI(Next.js)에서 CRUD**로 관리합니다.
- `holdings.yaml`은 다음 용도로 사용합니다.
  - 초기 이관(import)
  - 백업(export)

## 파일 구조

```yaml
version: 1

holdings:
  - ticker: "005930"
    quantity: 12
    entry_price: 71200
    entry_currency: KRW
    entry_date: 2024-09-12
    notes: "장기 보유"
    tags: [core, semiconductor]
```

### 필드 설명

| 필드 | 타입 | 설명 |
|------|------|------|
| `ticker` | string | 종목 식별자. 국내는 **6자리 숫자 코드 문자열**(예: `"005930"`), 해외는 `티커.거래소`(예: `TSLA.NAS`, `AAPL.NYS`) |
| `quantity` | number | 보유 수량. DB는 `numeric(20,6)`(`>=0`)로 강제하고, Python 로더에서는 `float`로 처리합니다. |
| `entry_price` | number | 평균 매입가 (기본 통화). DB는 `numeric(20,4)`(`>=0`)이며, `quantity>0` row는 `entry_price>0`을 요구합니다. |
| `entry_currency` | string (선택) | 통화 표시 (예: `KRW`, `USD`). 수동 작성 파일에서는 US-only + `settings.default_currency: USD`일 때만 row 생략 허용. 웹 export는 모든 row에 명시적으로 기록 |
| `entry_date` | string (YYYY-MM-DD) | 최초(또는 평균) 매입일 |
| `entry_pattern` | string (선택) | buy/entry report의 `pattern`을 보존하는 진입 패턴 marker. 허용값은 `trend_pullback_bounce`, `swing_high_breakout`, `rsi_oversold_reversal`입니다. 현재 로컬 CLI 로더/sell 평가 입력용이며, 웹 import/export와 scheduled holdings export는 Phase A에서 non-null 값을 보존하지 않습니다. |
| `strategy` | string (선택) | 전략 구분 (예: `swing`, `core`). 미지정 시 `settings.default_strategy` 적용 |
| `notes` | string (선택) | 메모 |
| `tags` | list[string] (선택) | 태그 목록 |
| `stop_override` | float (선택) | 사용자 정의 손절가 (`0` 이상만 허용) |
| `target_override` | float (선택) | 사용자 정의 목표가 (`0` 이상만 허용) |

## settings 블록 (선택)

```yaml
settings:
  default_currency: KRW
  default_strategy: swing
  default_tags:
    - watch
```

- `default_currency`: `entry_currency` 미지정 시 사용
- `default_strategy`: `strategy` 미지정 시 사용
- `default_tags`: 태그 미지정 시 초기값으로 사용
- 웹 UI export는 `settings`를 쓰지 않고 row별 명시 값만 기록합니다. `settings` 블록은 수동 작성/import와 로컬 CLI 입력에서 계속 지원됩니다.

### Fail-closed 통화 규칙

- US-only 보유 파일에서는 `settings.default_currency`를 `USD`(또는 미지정)로만 허용합니다.
- US-only + `settings.default_currency: USD`인 경우, row별 `entry_currency` 생략 시 `USD`로 처리합니다.
- US/KR 혼합 보유 파일에서는 `settings.default_currency` 사용을 금지하고 row마다 `entry_currency`를 명시해야 합니다.
- US 티커의 유효 통화는 항상 `USD`여야 하며, `USD`가 아닌 값은 즉시 실패합니다.
- KR-only 보유 파일에서 `settings.default_currency: USD`는 즉시 실패합니다.
- `entry_currency: USD`를 쓸 때는 티커도 US suffix를 가져야 합니다(예: `AAPL.NAS`).
- `entry_currency` 허용값은 `KRW`, `USD`만 지원합니다. 그 외 값(`EUR` 등)은 즉시 실패합니다.

### Fail-closed entry_pattern 규칙

- `entry_pattern`은 `trend_pullback_bounce`, `swing_high_breakout`, `rsi_oversold_reversal`만 허용합니다.
- 빈 문자열, 공백 문자열, 명시적 `null`, 미지정은 모두 marker 없음으로 처리합니다.
- 비활성 row(`quantity=0`)는 `entry_pattern`을 가질 수 없습니다. 미지정 또는 null/empty로 남겨야 합니다.
- `sab sell`은 로드된 `entry_pattern`을 hybrid sell evaluator에 전달합니다. 현재 failed-breakout 손실 marker로 쓰이는 구조화 값은 `swing_high_breakout`뿐이며, 기존 `strategy`/`tags`의 `breakout` substring marker는 호환용으로 계속 동작합니다.
- Phase A Supabase migration은 nullable `holdings.entry_pattern` 컬럼과 RPC 검증 계약을 추가하지만, `holdings_entry_pattern_write_closed_check`로 non-null DB write를 막습니다. 웹 CRUD, 웹 YAML import/export, scheduled holdings export가 필드를 선택/쓰기 전까지 DB는 null-only입니다.

## 웹 import/export 계약

- Holdings 화면의 `Export YAML`은 항상 `version: 1` 문서를 생성합니다.
- export는 현재 DB의 전체 snapshot을 내보내며, `quantity=0` 비활성 row도 포함합니다.
- export는 복구 충실도를 위해 `settings`를 생략하고 row별 필드를 명시합니다.
- export 정렬 순서는 `ticker asc`입니다.
- Phase A에서는 웹 export/import payload가 `entry_pattern`을 소유하지 않습니다. 로컬 CLI 입력에는 사용할 수 있지만, 웹 import/export 백업 경로로 non-null marker를 왕복시키는 것은 아직 지원하지 않습니다.
- Holdings 화면 import는 항상 **Replace All** semantics로 동작합니다.
- import는 apply 전에 dry-run diff(create/update/delete/unchanged)를 보여줍니다.
- import apply 시 파일에 없는 ticker는 삭제됩니다.
- import apply는 서버에서 검증 후 원자적으로 반영되며, unchanged row는 갱신하지 않습니다.

### Fail-closed 티커 규칙

- `ticker`가 suffix 없이 입력된 경우, KR 숫자 코드만 허용됩니다(예: `005930`).
- KR 숫자 코드는 6자리만 허용됩니다(예: `005930`).
- `AAPL`처럼 suffix 없는 영문 티커는 즉시 실패합니다.
- `.US` suffix는 모호성 방지를 위해 허용되지 않으며, `.NAS/.NYS/.AMS`처럼 거래소를 명시해야 합니다.
- Supabase `holdings` 테이블도 동일 계약을 강제하며, 기존 `.US` row는 자동 변환하지 않고 수동 정리 대상으로 취급합니다.
- US 클래스 티커는 `BASE.CLASS.EXCH`를 캐노니컬로 사용합니다(예: `BRK.B.NYS`).
- `BRK/B.NYS` 입력은 허용되지만 내부 저장/평가 시 `BRK.B.NYS`로 정규화됩니다.
- `AAPL.XNAS`처럼 지원되지 않은 suffix는 즉시 실패합니다.
- KR 숫자 코드는 YAML 파서에서 앞자리 0이 소실되지 않도록 문자열로 적어야 합니다(예: `ticker: "005930"`).
- `stop_override`, `target_override`는 `0` 이상만 허용되며, 음수 값은 즉시 실패합니다.

## 예시 파일

- 리포지토리 루트에 있는 `holdings.example.yaml` 참조
- 기본 경로는 `config.yaml`의 `files.holdings` 또는 `.env`의 `HOLDINGS_FILE`로 설정할 수 있습니다.
- `files.holdings`/`HOLDINGS_FILE` 경로를 지정했는데 파일이 없으면 로더는 즉시 실패합니다.

## 활용

- `sab sell` 서브커맨드는 `holdings.yaml`을 로드하여 보유 종목의 Sell/Review 리포트를 생성합니다.
- 로컬 `holdings.yaml`에 `entry_pattern`이 있으면 `sab sell`이 hybrid sell 평가로 전달합니다.
- `holdings.example.yaml`을 복사해 개인 보유 목록을 작성한 뒤, `HOLDINGS_FILE` 또는 `config.yaml`의 `files.holdings` 경로를 지정하세요.

## 백로그 메모

- `settings` 블록에 전략별 기본 임계치(`defaults.strategy` 등)를 추가해 자동 평가 가중치를 조절할 수 있도록 확장 가능.
