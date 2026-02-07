# 설계 — 리포트(Markdown)

용도별 3가지 리포트를 생성하며, 날짜와 접미사를 사용합니다. 같은 날 여러 번 생성 시 `-1`, `-2`가 붙습니다.

- Buy Report: `reports/YYYY-MM-DD.buy.md`
- Sell/Review Report: `reports/YYYY-MM-DD.sell.md`
- Entry Check Report: `reports/YYYY-MM-DD.entry.md`(계획)

## 공통 헤더

```
# <Title> — YYYY-MM-DD
- Run at: YYYY-MM-DD HH:MM <TZ>
- Provider: kis (cache: hit|refresh|expired|pykrx)
- Universe/Evaluated: counts
- Notes: N issue(s) logged (see Appendix)  # only when present
```

## Buy Report

- 후보 테이블(기본 EMA 전략):
  - 컬럼: Ticker | Name | Price | EMA20 | EMA50 | RSI14 | ATR14 | Gap | Score
- 후보 테이블(하이브리드 전략 모드 — 계획):
  - 컬럼 예: Ticker | Name | Price | SMA20 | EMA10 | EMA21 | RSI14 | Vol(5d) | Pattern | Score
- 후보 상세:
  - 공통: 가격 스냅샷, EMA/SMA 컨텍스트, RSI, ATR, 갭 임계, 유동성 요약, 리스크 가이드(ATR 스톱), 스코어 노트
  - 하이브리드 모드(계획): 패턴 유형(눌림 반등/돌파/RSI 반등), 체크리스트(예: Close>SMA20, EMA10≥EMA21, RSI 범위, 거래량 증가)를 항목으로 추가
- 해외 종목: `FX_MODE=kis`일 때 KIS `price-detail`에서 실시간 환율을 가져와 USD 가격과 원화 환산 값을 병기하며, 환율(1 USD ≈ ₩X, 소스/캐시 상태 포함) 메모를 추가한다. 실패 시 `USD_KRW_RATE` 값으로 폴백하거나 환율 미표시 경고를 Appendix에 남긴다.
- Appendix: 실패/보류(예: 히스토리 부족, SMA200/하이브리드 필터, ETF 제외, API 오류 및 폴백 기록)

## Sell/Review Report

- 요약: Ticker | Qty | Entry | Last | P/L% | State | Stop | Target
- 보유 상세: 포지션 요약, 전일 종가, P/L, 리스크 가이드, 노트, 사유 목록(중요도 순)
- 메타데이터: 헤더에 주요 규칙 파라미터 표기(예: ATR×k, 시간 스톱 일수)

## Entry Check(계획)

- 전일 Buy 후보를 기준으로 당일 시초 갭/ATR을 비교해 OK/Wait/Avoid 표기, 필요 시 장초 스냅샷(1/3/5/15분) 요약 포함

## 서식

- 숫자: 가격은 천단위 구분, 지표는 소수 1자리, 변화율은 % 표기
- 시간: 헤더는 실행 환경의 로컬 타임존 라벨, US 스크리너 메타는 ET 상태
- 5분 내 훑어볼 수 있도록 간결한 리스트 중심 구성
