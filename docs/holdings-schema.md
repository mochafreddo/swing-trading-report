# holdings.yaml Schema (Draft)

이 문서는 `holdings.yaml` 파일 구조를 정의합니다. 보유 종목을 기록하여 Sell/Review 평가에 활용할 수 있습니다.

## 파일 구조

```yaml
version: 1

holdings:
  - ticker: 005930
    quantity: 12
    entry_price: 71200
    entry_date: 2024-09-12
    notes: "장기 보유"
    tags: [core, semiconductor]
```

### 필드 설명

| 필드 | 타입 | 설명 |
|------|------|------|
| `ticker` | string | 종목 식별자. 국내는 숫자, 해외는 `티커.거래소`(예: `TSLA.US`) |
| `quantity` | int/float | 보유 수량 |
| `entry_price` | float | 평균 매입가 (기본 통화) |
| `entry_currency` | string (선택) | 통화 표시 (예: `KRW`, `USD`). 미지정 시 `settings.default_currency` 적용 |
| `entry_date` | string (YYYY-MM-DD) | 최초(또는 평균) 매입일 |
| `strategy` | string (선택) | 전략 구분 (예: `swing`, `core`). 미지정 시 `settings.default_strategy` 적용 |
| `notes` | string (선택) | 메모 |
| `tags` | list[string] (선택) | 태그 목록 |
| `stop_override` | float (선택) | 사용자 정의 손절가 |
| `target_override` | float (선택) | 사용자 정의 목표가 |

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

## 예시 파일

- 리포지토리 루트에 있는 `holdings.example.yaml` 참조
- 기본 경로는 `config.yaml`의 `files.holdings` 또는 `.env`의 `HOLDINGS_FILE`로 설정할 수 있습니다.

## 활용

- `uv run -m sab sell` 서브커맨드는 `holdings.yaml`을 로드하여 보유 종목의 Sell/Review 리포트를 생성합니다.
- `holdings.example.yaml`을 복사해 개인 보유 목록을 작성한 뒤, `HOLDINGS_FILE` 또는 `config.yaml`의 `files.holdings` 경로를 지정하세요.

## 향후 확장 아이디어

- `settings` 블록에 전략별 기본 임계치(`defaults.strategy` 등)를 추가해 자동 평가 가중치를 조절할 수 있도록 확장 가능.
