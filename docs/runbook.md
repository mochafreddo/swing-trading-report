# 런북 — CLI 운영 가이드

로컬에서 CLI를 실행/디버그/운영하기 위한 실무 지침입니다.

## 설치/준비

- uv 설치: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- 의존성 동기화: `uv lock && uv sync`
- 설정:
  - `config.yaml` 생성(기본값은 `config.example.yaml` 참고)
  - `.env`에 KIS 키/토글 작성
  - 선택: `uv sync --extra pykrx`로 KR 폴백/프로바이더 활성화

## 자주 쓰는 실행

- Buy 스캔(KR+US 스크리너 + 워치리스트)
  - `uv run -m sab scan --universe both`
- Buy 스캔(스크리너만, 상위 20)
  - `uv run -m sab scan --universe screener --screener-limit 20`
- 보유 매도/보류 평가
  - `uv run -m sab sell`

## 파일/경로

- 리포트: `reports/YYYY-MM-DD.buy.md`, `...sell.md`(중복 시 `-1`)
- 캐시/상태: `data/`(KIS 토큰, 캔들, 스크리너 캐시)
- 보유 목록: `holdings.yaml`(경로는 `files.holdings` 또는 `HOLDINGS_FILE`)

## 문제 해결

- 토큰 오류/401: `KIS_APP_KEY/SECRET/BASE_URL` 확인, `data/kis_token_*` 삭제로 강제 갱신(24시간 정책 유의)
- 레이트리밋 `EGW00201`: `KIS_MIN_INTERVAL_MS`(예: 500–1000) 증가 후 재시도. 스크리너 TTL도 호출 수 절감에 도움
- 히스토리 부족: `MIN_HISTORY_BARS=200+` 권장, 누적 수집으로 보완. 신규상장 등은 기준 미달 가능
- US 심볼: `SYMBOL.US` 또는 `SYMBOL.NASD/NYSE/AMEX` 사용. US에는 PyKRX 폴백이 적용되지 않음
- US 스크리너: `screener.us_mode=kis`로 KIS 랭크 사용. 실패 시 `screener.us_defaults`로 자동 폴백
- 환율/통화: `FX_MODE=kis`(기본)로 설정하면 KIS 해외 현재가상세에서 `t_rate`를 받아 자동 환율을 적용하고, `FX_CACHE_TTL`분 동안 캐시합니다. 실패 시 `USD_KRW_RATE` 값으로 폴백하거나, 값이 없으면 리포트 Appendix에 경고를 남깁니다.
- 휴장일: 미국 휴일 정보는 KIS `countries-holiday` API를 조회해 `data/holidays_us.json`에 캐시합니다. 파일을 삭제하면 다음 실행 시 자동 갱신됩니다.

## 확장

- RS 벤치마크: 지수 클라이언트를 추가해 시장별 `rs_benchmark_return`을 동적으로 주입
- Entry 체크: 시초/1–15분 데이터를 받아 OK/Wait/Avoid 규칙을 `sab/entry.py`에 구현
