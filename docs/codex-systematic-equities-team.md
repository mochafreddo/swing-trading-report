# Codex Systematic Equities Team

상태: Accepted  
대상: 저장소 로컬 Codex plugin/skill 운영

## 문서 상태

### 현재 제공

- `plugins/systematic-equities-team` plugin과 세 개의 역할 skill은 저장소 안에 배포되어 있습니다.
- docs 인덱스와 plugin marketplace manifest가 현재 연결된 상태를 유지합니다.

### 실험

- 별도 experimental role은 운영 기준에 포함하지 않습니다.

### 백로그

- 새 역할 추가는 실제 반복 작업과 소유 파일 경계가 분명해질 때만 검토합니다.

### 폐기 후보

- 기존 역할과 책임이 겹치는 일반론 skill을 추가로 늘리는 방향은 채택하지 않습니다.

## 목적

이 문서는 `swing-trading-report` 안에서 바이사이드 systematic equities 팀처럼 작동할 수 있도록 추가한 Codex 역할 구성을 설명합니다.

구성은 Context7로 확인한 Codex 공식 구조를 따릅니다.

- 재사용 가능한 전문 에이전트는 `skill`로 제공
- 프로젝트 로컬 배포는 `plugin + skills` 구조로 묶음

구현 경로:

- plugin: `plugins/systematic-equities-team`
- marketplace 등록: `.agents/plugins/marketplace.json`

## 역할

### `$swing-quant-researcher`

- 용도: 진입/스캔 신호 로직, 레짐 필터, 임계값, 가설 검증
- 강한 파일: `docs/STRATEGY.md`, `sab/signals/*`, 관련 회귀 테스트
- 비목표: 웹 UI, 인증, CRUD, 인프라 전용 문제

### `$swing-risk-portfolio-manager`

- 용도: sell/review/entry guard, 손절/익절, time stop, 액션 임계값
- 강한 파일: `sab/signals/hybrid_sell.py`, `sab/signals/sell_rules.py`, `sab/entry.py`
- 비목표: 순수 알파 발굴, 데이터 수집 계층 자체 검증

### `$swing-data-backtest-engineer`

- 용도: 데이터 정합성, adjusted/raw 경계, 캐시 신선도, 캘린더, 재현성, 백테스트 근거
- 강한 파일: `sab/market_data_pipeline.py`, `sab/market_data_service.py`, `sab/data/*`, 관련 테스트
- 비목표: UI 개선, 단순 문구 조정

## 권장 협업 순서

1. 신호 변경 제안은 `$swing-quant-researcher`로 시작합니다.
2. 손실 통제나 action 기준이 바뀌면 `$swing-risk-portfolio-manager`가 확인합니다.
3. 데이터 신선도, 재현성, fixture, provider 경계가 걸리면 `$swing-data-backtest-engineer`가 검증합니다.

세 역할은 서로 대체 관계가 아니라 handoff 관계입니다.

## 예시 프롬프트

- `Use $swing-quant-researcher to review whether a new breakout filter belongs in hybrid_buy.py.`
- `Use $swing-risk-portfolio-manager to check if this ATR trailing stop change loosens exits too much.`
- `Use $swing-data-backtest-engineer to validate whether this adjusted/raw refactor preserves reproducible entry evaluation.`

## 운영 메모

- skill은 자동 호출되거나 명시적으로 `$skill-name`으로 호출할 수 있습니다.
- 각 skill은 영향 파일을 끝까지 읽고, 작은 안전 변경과 회귀 테스트를 우선하도록 설계했습니다.
- 외부 라이브러리나 Codex 동작 규약 확인이 필요하면 Context7을 먼저 사용합니다.
