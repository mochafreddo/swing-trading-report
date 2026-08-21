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
- 로컬 Python 로더, Supabase holdings, 웹 CRUD/YAML import/export, scheduled export는 선택적 `entry_pattern`을 보존해 sell 평가에 전달합니다.

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
| `entry_pattern` | string/null (선택) | buy/entry report의 `pattern`을 보존하는 active-position marker. 허용값은 `trend_pullback_bounce`, `swing_high_breakout`, `rsi_oversold_reversal`입니다. 웹 export는 `null`도 명시하고, import/create/patch는 non-null marker를 active row(`quantity > 0`)에만 허용합니다. |
| `strategy` | string (선택) | 전략 구분 (예: `swing`, `core`). 미지정 시 `settings.default_strategy` 적용 |
| `notes` | string (선택) | 메모 |
| `tags` | list[string] (선택) | 태그 목록. `portfolio.exposure_limits`가 활성화된 경우 `sector:semiconductor`, `theme:ai`, `beta:high_beta`, `correlation:ai-megacap` 같은 prefix 태그는 활성 보유의 노출 bucket으로도 해석됩니다. |
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

### Decision Board V0 SWING 승인 경계

Decision Board의 US HOLDING shadow 입력은 수동 YAML 기본값이 아니라 검증된 `BrokerSnapshotV0` 행의 `strategy`만 사용합니다. ASCII 공백 제거와 대소문자 정규화 뒤 값 자체가 ASCII-only이고 정확히 `SWING`이며, `quantity > 0`이고 `broker_state=confirmed`인 행만 identity gate로 전달됩니다. strategy가 없거나 `swing_breakout`, `long_swing`, `CORE`, `LONG_TERM`처럼 정확히 일치하지 않으면 `REVIEW_STRATEGY_NOT_APPROVED`가 되고 방향성 HOLD/SELL 입력이 되지 않습니다. Unicode case folding으로 비슷해 보이는 문자, fullwidth 문자, zero-width/bidi format 문자를 포함한 값도 `SWING`으로 간주하지 않습니다. `settings.default_strategy`, tags, notes는 이 승인을 대신할 수 없습니다.

승인 결과에는 공개 종목 identity만 남고 quantity, entry price, P/L, notes, tags, account 정보와 원본 holding payload는 research 입력에 포함되지 않습니다. identity는 호출자가 주입한 명시적 versioned registry에서만 결정하며, 미등록 ticker나 모호한 거래소 표기는 REVIEW로 닫힙니다.

### 포트폴리오 노출 태그

- `sab entry`는 활성 holdings의 `tags`에서 `sector:`, `theme:`, `beta:`/`beta_bucket:`, `correlation:`/`correlation_bucket:` prefix를 읽어 포트폴리오 노출 bucket으로 계산합니다.
- 예를 들어 holdings row에 `tags: [sector:semiconductor, theme:ai]`가 있고 `portfolio.exposure_limits`에 `dimension: sector`, `value: semiconductor`, `max_active: 2`가 있으면, 같은 sector bucket의 신규 `ENTER` 후보는 기존 활성 보유 2개 이후 `SKIP`됩니다.
- prefix가 없는 일반 tag도 `dimension: tag` limit의 bucket 값으로 사용할 수 있습니다.

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
- Supabase `holdings.entry_pattern`은 nullable이며 length/allowlist/active-only constraint를 갖습니다. `replace_holdings_v1`은 active row에서 key가 생략되면 기존 marker를 보존하지만, entry identity(`entry_price`, `entry_date`) 또는 `strategy`가 바뀌는 active row는 명시적 valid marker나 명시적 clear(`null`/blank)를 요구합니다.

## 웹 import/export 계약

- Holdings 화면의 `Export YAML`은 항상 `version: 1` 문서를 생성합니다.
- export는 현재 DB의 전체 snapshot을 내보내며, `quantity=0` 비활성 row도 포함합니다.
- export는 복구 충실도를 위해 `settings`를 생략하고 row별 필드를 명시합니다.
- export 정렬 순서는 `ticker asc`입니다.
- export는 `entry_pattern`을 항상 명시합니다. DB 값이 `null`이어도 `entry_pattern: null`을 기록해, 나중에 import할 때 cleared marker가 old-style omitted key로 바뀌지 않게 합니다.
- import 입력에서 `entry_pattern` key 생략은 old YAML 호환을 위한 active-row preserve-existing 의미입니다. 명시적 `null` 또는 blank는 clear이고, non-empty string은 set입니다. `quantity=0` row는 import/apply 시 `entry_pattern=null`로 정규화됩니다.
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
