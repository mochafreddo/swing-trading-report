# Project Overview

상태: Accepted (개요)

`swing-trading-report`는 KR/US 주식 시장의 스윙 트레이딩 후보를 선별하고, 보유 종목을 점검하고, 진입 후보를 AI Brief로 요약하는 단일 사용자 운영 도구입니다. 자동 주문 시스템이 아니라 사람이 검토할 JSON 리포트와 로컬 웹 콘솔을 만드는 시스템입니다.

## 문서 상태

### 현재 제공

- 시스템 목적, 주요 사용자, 도메인 용어, 운영 흐름을 설명합니다.
- 구현 세부는 [Architecture](ARCHITECTURE.md), 실행 절차는 [Local Development](local-development.md), 운영 절차는 [Operations](operations.md)를 우선합니다.

### 실험

- US SWING Decision Board V0는 explicit live-shadow adapter가 구현됐지만 schedule은 비활성인 advice-only shadow입니다. [reference](decision-board.md)와 [20-session 평가 절차](decision-board-shadow-evaluation.md)를 통과하기 전 production owner가 아닙니다.

### 백로그

- 원격 공개 운영, 멀티유저 권한 모델, 자동 주문 연동은 별도 설계가 필요합니다.

### 폐기 후보

- 현재 계약과 맞지 않는 과거 PRD식 장문 요구사항을 이 문서에 되살리지 않습니다.

## 주요 사용자

| 사용자 | 필요한 정보 | 시작 문서 |
| --- | --- | --- |
| 신규 개발자 | 설치, 실행, 테스트, 구조 | [Local Development](local-development.md), [Architecture](ARCHITECTURE.md) |
| 운영자 | 로그, 헬스체크, scheduled run, 장애 초동 | [Operations](operations.md), [Troubleshooting](troubleshooting.md) |
| SI 인수인계자 | 컴포넌트, 데이터 저장소, 배포/복구 절차 | [Architecture](ARCHITECTURE.md), [Deployment](deployment.md) |
| 전략 변경자 | 신호/리스크 계약, fixture, 회귀 테스트 | [STRATEGY](STRATEGY.md) |

## 시스템이 하는 일

1. `sab scan`이 watchlist와 screener 후보를 평가해 `buy` 리포트를 생성합니다.
2. `sab sell`이 Supabase 또는 `holdings.yaml` 기반 보유 종목을 평가해 `sell` 리포트를 생성합니다.
3. `sab entry`가 `buy` 리포트 후보를 다음 세션 진입 관점으로 재평가해 `entry` 리포트를 생성합니다.
4. `sab backtest`가 로컬 historical OHLCV 파일을 기존 buy/sell 전략 로직으로 replay해 `backtest` 연구 리포트를 생성합니다.
5. `sab ai-brief`가 `entry` 리포트의 recommendable/watch 후보를 source/news/model provider로 요약해 `ai-brief` 리포트를 생성합니다.
6. Next.js 웹 UI가 Supabase `report_index`, Storage, `holdings`, `runtime_state`를 조회/수정합니다.
7. GitHub Actions와 로컬 Docker scheduler가 정기 실행, 업로드, 알림, cleanup을 담당하고, macOS `launchd` Toss runner가 local scheduled holdings sync를 호출합니다.
8. Decision Board V0는 US SWING ENTRY/HOLDING public fact를 별도 local shadow report로 compile하고 Reports UI에서 보여줍니다. 기본 executor는 production adapter 미연결로 fail closed하며 기존 실행·알림을 바꾸지 않습니다.

## 핵심 용어

| 용어 | 의미 |
| --- | --- |
| `buy` report | scan 단계에서 만든 매수 후보 JSON |
| `sell` report | 보유 종목 매도/점검 후보 JSON |
| `entry` report | buy 후보의 다음 세션 진입 가능성 JSON |
| `backtest` report | 로컬 OHLCV로 과거 구간의 신호/거래/성과를 재현한 연구 JSON |
| `ai-brief` report | entry 후보의 AI 요약/추천 JSON |
| `ai-brief-skip` report | scheduled runtime guard로 실행이 중단됐음을 기록하는 JSON |
| `decision-board` report | US SWING ENTRY/HOLDING advice-only shadow JSON |
| `RunJournalV0` | local shadow의 planned/started/terminal/missed/stale 상태 기록 |
| `report_index` | 웹 목록/검색용 Supabase Postgres 테이블 |
| `runtime_state` | 로그인 throttle, scheduler lock/marker 같은 단기 상태 테이블 |
| `holdings` | 보유 목록의 운영 source of truth인 Supabase 테이블 |
| `watchlist.txt` | 로컬 수동 후보 티커 목록 |
| KIS | 한국투자증권 Open API 데이터 제공자 |

## 운영 원칙

- 리포트와 보유 목록은 사람이 검토하기 위한 의사결정 보조 자료입니다.
- Decision Board를 포함한 모든 매수·매도는 사용자가 직접 실행합니다.
- 시크릿은 `.env`/GitHub Secrets/운영 환경변수에 두고 문서와 코드에 실제 값을 쓰지 않습니다.
- 문서와 코드가 충돌하면 실제 코드, 실행 설정, CI, 테스트, 환경변수 예시, 현재 문서, 추론 순서로 판단합니다.
- 운영 담당자, 실제 에스컬레이션 채널, 원격 production 운영 정책은 코드만으로 확인할 수 없으므로 `NEEDS_CONFIRMATION` 대상입니다.

## 관련 문서

- 구조: [Architecture](ARCHITECTURE.md)
- 설정: [Configuration](configuration.md)
- 배포: [Deployment](deployment.md)
- 운영: [Operations](operations.md)
- 장애 대응: [Troubleshooting](troubleshooting.md)
- Decision Board: [Reference](decision-board.md), [Shadow evaluation](decision-board-shadow-evaluation.md)
