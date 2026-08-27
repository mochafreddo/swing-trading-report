# Product Backlog — Swing Trading Report

상태: Backlog (제품 방향/축약)

이 문서는 현재 계약 문서가 아닙니다. 제품 방향과 아직 남은 의사결정만 짧게 보존합니다. 현재 동작 기준은 [README](../README.md), [문서 인덱스](README.md), [아키텍처](ARCHITECTURE.md), [전략](STRATEGY.md), [Spec v1.1](spec-v1.1.md)을 우선합니다.

## 문서 상태

### 현재 제공

- 로컬 `scan`/`sell`/`entry`/`ai-brief` JSON 리포트 생성과 웹 Reports/Holdings/Metrics는 현재 제공됩니다.
- `scan`/`sell` GitHub Actions workflow는 manual-only `workflow_dispatch`로 제공됩니다. scheduled scan과 GitHub scheduled sell은 marker-aware fallback 설계 전까지 fail closed 상태입니다.
- scheduled AI Brief는 로컬 Docker primary가 담당하고, `.github/workflows/ai-brief.yml`은 수동 실행과 monitor/fallback 경로로 사용합니다.
- scheduled Sell AI Brief generation은 Toss freshness marker가 있을 때 로컬 generic wrapper가 담당하며, 정상 판단 전송과 freshness-blocked 보류 알림을 분리합니다.
- US SWING Decision Board V0의 public identity, bounded research, exact-span claim validation, pure compiler, local runner/report/RunJournal, Supabase index와 Reports UI 계약은 구현되어 있습니다. 기본 `decision-board` CLI는 계속 `CONFIG_UNAVAILABLE`로 fail closed하고, 별도 승인된 local `decision-board-shadow-live`와 exact-slot heartbeat만 gitignore된 승인 manifest 기간에 실행됩니다.

### 실험

- US SWING Decision Board는 advice-only shadow 실험입니다. 사전 승인된 20 US 거래 session gate가 진행 중이며, diff taxonomy와 전체 수동 졸업 검토를 통과하기 전 production owner가 될 수 없습니다. 진행률은 local journal/report를 `decision-board-shadow-evaluate`로 read-only 집계해 확인합니다.
- 전략/파라미터 실험은 [전략 문서](STRATEGY.md), replay fixture, 테스트에서 추적합니다.

### 백로그

- 웹 `Run` 탭과 GitHub Actions workflow에 standalone `entry` 전용 실행 경로 추가
- 원격 노출/클라우드 상시 운영 같은 운영 모델 확장 여부 결정
- 장 오픈 진입 가이드(ORH/첫 눌림 재상승 등) 텍스트 보강
- 추가 유료/벤더별 news/API adapter 운영화 여부 결정
- 승인된 Decision Board 20-session shadow gate를 누적하고 기간 종료 뒤 수동 졸업 검토 자료를 완성

### 폐기 후보

- `watchlist.yaml` 메모형 입력 포맷
- `uv init` 기준의 초기화 설명처럼 현재 저장소 구조와 맞지 않는 부트스트랩 절차
- 현재 계약을 이 PRD에 중복 서술하는 방식

## 1. 제품 방향

- 차트를 계속 보지 않아도 KR/US 스윙 후보와 보유 종목 상태를 빠르게 점검한다.
- 실행 결과는 사람이 재검토할 수 있는 JSON 리포트로 남기고, 로컬 웹에서 탐색한다.
- 자동 매매가 아니라, 후보 선별과 판단 보조를 목표로 한다.
- Decision Board를 포함한 모든 매수·매도는 사용자가 직접 실행한다. 주문 생성·수정·취소·조건부 주문 capability는 제품 범위에 넣지 않는다.
- 개인/단일 사용자 로컬 운영을 기본으로 하며, 원격 공개 운영은 별도 설계와 보안 검토 전까지 범위 밖으로 둔다.

## 2. 사용자와 성공 기준

- 대상 사용자: 단일 maintainer/운영자.
- 성공 기준:
  - 신규 개발자는 README에서 시작해 로컬 실행, 테스트, 구조, 운영 문서로 이동할 수 있다.
  - 운영자는 Operations/Troubleshooting에서 장애 시작점과 복구 확인 방법을 찾을 수 있다.
  - 전략 변경자는 STRATEGY와 관련 테스트를 기준으로 영향 범위를 판단할 수 있다.

## 3. 현재 계약의 위치

| 질문 | Source of truth |
| --- | --- |
| 프로젝트 개요, 빠른 시작, 주요 명령 | [README](../README.md) |
| 로컬 실행 | [Local Development](local-development.md) |
| 배포/롤백 | [Deployment](deployment.md) |
| 운영 체크/장애 대응 | [Operations](operations.md), [Troubleshooting](troubleshooting.md) |
| 시스템 구성과 데이터 흐름 | [ARCHITECTURE](ARCHITECTURE.md) |
| 신호/리스크 전략 로직 | [STRATEGY](STRATEGY.md) |
| Decision Board 구현/CLI/report 계약 | [Decision Board V0](decision-board.md) |
| Decision Board shadow 졸업 측정 | [Shadow evaluation](decision-board-shadow-evaluation.md) |
| Storage/report_index/runtime_state 계약 | [Spec v1.1](spec-v1.1.md) |
| 환경변수와 config override | [config-reference](config-reference.md), [`.env.example`](../.env.example) |

## 4. 남은 제품 질문

- standalone `entry` 실행을 웹 `Run` 탭과 GitHub Actions에 추가할 때, `scan`/`sell`과 같은 단순 dispatch로 충분한가, 아니면 buy report 선택 UX가 먼저 필요한가?
- 로컬 전용 웹을 원격으로 노출할 필요가 생기면, 현재 local-request guard가 아니라 별도 인증/권한/비밀 관리 모델을 어떻게 둘 것인가?
- AI Brief source provider는 어떤 품질 기준을 통과해야 기본 provider로 승격할 수 있는가?
- Decision Board provider/coverage/freshness threshold를 첫 shadow gate manifest에서 어떤 수치로 사전 승인할 것인가?
- 20-session gate 통과 뒤에도 notification/schedule owner 전환은 어떤 별도 승인과 rollback rehearsal을 요구할 것인가?
- 전략/리스크 변경 backlog는 제품 문서가 아니라 [STRATEGY](STRATEGY.md)와 테스트 fixture에서 추적하는 것이 더 적합한가?

## 5. 보존 메모

- 기존 긴 PRD(v1.2 시점 요구사항/로드맵/AC)는 현재 구현과 중복되고 drift 위험이 있어 이 축약 문서로 대체했습니다.
- 과거 상세 문구가 필요하면 Git history에서 이 파일의 이전 버전을 확인하세요.
