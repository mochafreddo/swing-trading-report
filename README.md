# Swing Trading Report (KR, On‑Demand)

간단한 스윙 스크리닝을 원할 때만 실행하고, 결과를 마크다운 리포트로 저장하는 개인용 로컬 프로젝트입니다. 데이터 소스는 기본적으로 한국투자증권 KIS Developers(Open API)를 사용합니다. 프로젝트/의존성 관리는 uv를 사용합니다.

상세 배경과 요구사항은 PRD.md 참고.

## Quickstart (uv 기반)

- uv 설치(macOS)
  - `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - 확인: `uv --version`

- 의존성/프로젝트 준비
  - 기존 저장소라면 `pyproject.toml` 추가 후 의존성 동기화
  - 예시: `uv add requests pandas numpy python-dotenv`
  - 잠금/동기화: `uv lock && uv sync`

- .env 설정(예시)
  - `DATA_PROVIDER=kis`
  - `KIS_APP_KEY=...`
  - `KIS_APP_SECRET=...`
  - `KIS_BASE_URL=...`  # 모의/실전 (포트 생략 가능: 자동으로 9443/29443 보정)
  - `SCREEN_LIMIT=30`
  - `REPORT_DIR=reports`
  - `DATA_DIR=data`
  - `SCREENER_ENABLED=true` (옵션, KIS 상위 종목 스크리너 활성화)
  - `SCREENER_LIMIT=30` (옵션, 스크리너 상위 N)
  - `SCREENER_ONLY=false` (옵션, true이면 스크리너 결과만 사용)

- 실행 예시
  - 기본 실행: `uv run -m sab scan`
  - 스크리너 크기 지정: `uv run -m sab scan --limit 30`
  - 워치리스트 지정: `uv run -m sab scan --watchlist watchlist.txt`

- 결과
  - `reports/YYYY-MM-DD.md` 생성. 포맷은 docs/report-spec.md 참고

참고: KIS 토큰은 1일 1회 발급 원칙입니다. 본 프로젝트는 토큰을 `data/`에 캐시해 같은 날 재발급을 피합니다.

## 파일/폴더 구조(예정)

- `sab/` … 애플리케이션 코드
  - `__main__.py` … CLI 엔트리(`sab scan`)
  - `data/` … KIS/PyKRX 커넥터, 캐시
  - `signals/` … EMA/RSI/ATR 계산
  - `report/` … 마크다운 템플릿 렌더링
- `reports/` … 생성된 마크다운 리포트 출력 폴더
- `data/` … 캐시/상태(JSON 또는 SQLite)
- `docs/kis-setup.md` … KIS 설정 가이드
- `docs/report-spec.md` … 리포트 스펙
- `PRD.md` … 제품 요구사항 문서

## 스크립트화 권장

반복 명령은 스크립트/Makefile로 캡슐화하면 편합니다.

- `bin/scan`
  - `uv run -m sab scan "$@"`
- `Makefile`
  - `scan`, `scan-limit`, `scan-watchlist`, `lock`, `sync` 등 타깃 정의

## 상태

- 문서 우선 정리 단계. 이후 KIS 클라이언트/CLI 스캐폴딩을 추가합니다.

## 라이선스

- 본 리포지토리의 소스코드는 MIT License를 따릅니다. 자세한 내용은 `LICENSE` 파일을 참조하세요.
- `open-trading-api/` 디렉터리는 한국투자증권 KIS Developers 공개 샘플로, 해당 프로젝트의 라이선스/약관을 따릅니다(해당 폴더의 README/라이선스 참고).

## 전략(요약)

- 코어: EMA20/50 골든크로스 + RSI14 30 상향 재돌파(+ RSI<70)
- 장기 필터(옵션): 가격/EMA20/EMA50 모두 SMA200 위
- 갭 필터: ATR 기반(|갭| ≤ ATR×배수 / 전일종가), 기본 배수 1.0 권장
- 품질: 최소 거래대금(최근 20일 평균), 신규상장/저유동 제외, ETF/ETN/레버리지 제외 옵션
- 품질 보강: EMA20/50 기울기>0, 신호일 종가가 두 EMA 위
- 리스크: ATR14 기반 손절/타깃(~1:2)
- 점수화: 추세/기울기/모멘텀/유동성/변동성 가중 합산으로 후보 정렬
