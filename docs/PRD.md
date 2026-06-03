# Product Backlog — Swing Trading Report

상태: Backlog (제품 방향/축약)

이 문서는 현재 계약 문서가 아닙니다. 제품 방향과 아직 남은 의사결정만
짧게 보존합니다. 현재 동작 기준은 [README](../README.md),
[런북](runbook.md), [아키텍처](ARCHITECTURE.md), [전략](STRATEGY.md),
[Spec v1.1](spec-v1.1.md)을 우선합니다.

## 문서 상태

### 현재 제공

- 로컬 `scan`/`sell`/`entry`/`ai-brief` JSON 리포트 생성과 웹
  Reports/Holdings/Metrics는 현재 제공됩니다.
- GitHub Actions `scan`/`sell` schedule 실행과 Telegram/Slack 요약 알림은
  현재 제공됩니다.
- scheduled AI Brief는 로컬 Docker primary가 담당하고,
  `.github/workflows/ai-brief.yml`은 수동 실행과 monitor/fallback 경로로
  사용합니다.

### 실험

- 별도 experimental 제품 문서는 운영하지 않습니다. 전략/파라미터 실험은
  [전략 문서](STRATEGY.md), replay fixture, 테스트에서 추적합니다.

### 백로그

- 웹 `Run` 탭과 GitHub Actions workflow에 standalone `entry` 전용 실행 경로
  추가
- 원격 노출/클라우드 상시 운영 같은 운영 모델 확장 여부 결정
- 장 오픈 진입 가이드(ORH/첫 눌림 재상승 등) 텍스트 보강
- 추가 유료/벤더별 news/API adapter 운영화 여부 결정

### 폐기 후보

- `watchlist.yaml` 메모형 입력 포맷
- `uv init` 기준의 초기화 설명처럼 현재 저장소 구조와 맞지 않는 부트스트랩
  절차
- 현재 계약을 이 PRD에 중복 서술하는 방식

## 1. 제품 방향

- 차트를 계속 보지 않아도 KR/US 스윙 후보와 보유 종목 상태를 빠르게
  점검한다.
- 실행 결과는 사람이 재검토할 수 있는 JSON 리포트로 남기고, 로컬 웹에서
  탐색한다.
- 자동 매매가 아니라, 후보 선별과 판단 보조를 목표로 한다.
- 개인/단일 사용자 로컬 운영을 기본으로 하며, 원격 공개 운영은 별도 설계와
  보안 검토 전까지 범위 밖으로 둔다.

## 2. 사용자와 성공 기준

- 대상 사용자: 단일 maintainer/운영자.
- 성공 기준:
  - 신규 개발자는 README에서 시작해 로컬 실행, 테스트, 구조, 운영 문서로
    이동할 수 있다.
  - 운영자는 runbook에서 장애 시작점과 복구 확인 방법을 찾을 수 있다.
  - 전략 변경자는 STRATEGY와 관련 테스트를 기준으로 영향 범위를 판단할 수
    있다.

## 3. 현재 계약의 위치

| 질문 | Source of truth |
| --- | --- |
| 프로젝트 개요, 빠른 시작, 주요 명령 | [README](../README.md) |
| 로컬 실행, 배포, 장애 대응 | [runbook](runbook.md) |
| 시스템 구성과 데이터 흐름 | [ARCHITECTURE](ARCHITECTURE.md) |
| 신호/리스크 전략 로직 | [STRATEGY](STRATEGY.md) |
| Storage/report_index/runtime_state 계약 | [Spec v1.1](spec-v1.1.md) |
| 환경변수와 config override | [config-reference](config-reference.md), [`.env.example`](../.env.example) |

## 4. 남은 제품 질문

- standalone `entry` 실행을 웹 `Run` 탭과 GitHub Actions에 추가할 때,
  `scan`/`sell`과 같은 단순 dispatch로 충분한가, 아니면 buy report 선택
  UX가 먼저 필요한가?
- 로컬 전용 웹을 원격으로 노출할 필요가 생기면, 현재 local-request guard가
  아니라 별도 인증/권한/비밀 관리 모델을 어떻게 둘 것인가?
- AI Brief source provider는 어떤 품질 기준을 통과해야 기본 provider로 승격할
  수 있는가?
- 전략/리스크 변경 backlog는 제품 문서가 아니라 [STRATEGY](STRATEGY.md)와
  테스트 fixture에서 추적하는 것이 더 적합한가?

## 5. 보존 메모

- 기존 긴 PRD(v1.2 시점 요구사항/로드맵/AC)는 현재 구현과 중복되고 drift
  위험이 있어 이 축약 문서로 대체했습니다.
- 과거 상세 문구가 필요하면 Git history에서 이 파일의 이전 버전을 확인하세요.
