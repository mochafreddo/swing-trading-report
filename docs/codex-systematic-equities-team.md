# Codex Systematic Equities Team

상태: Accepted  
대상: 저장소 로컬 Codex plugin/skill 운영

## 목적

이 문서는 `swing-trading-report` 안에서 바이사이드 systematic equities 팀처럼
작동할 수 있도록 추가한 Codex 역할 구성을 설명합니다.

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

