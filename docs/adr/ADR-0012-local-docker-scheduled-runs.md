## ADR-0012 — 시간 민감 scheduled 실행: 로컬 Docker primary + GitHub fallback

상태: 채택(Accepted)  •  날짜: 2026-05-28

### 배경

- `ai-brief` scheduled workflow는 US/KR 장전(`PRE_OPEN`) window 안에서만 의미가 있습니다.
- 2026-05-28 US scheduled AI Brief는 workflow cron을 `12:07 UTC`로 앞당긴 뒤에도 GitHub run이 `13:34 UTC`에 생성되어, guard 실행 시각이 `09:34 ET`가 되었습니다.
- 이 시점은 US 정규장 시작(`09:30 ET`) 이후이므로 workflow는 `session_state=INTRADAY`로 판정하고 AI Brief를 건너뛰었습니다.
- GitHub Actions `schedule` 이벤트는 고부하 때 지연되거나 드롭될 수 있으며, [GitHub 문서](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule)도 분산된 minute 사용을 권장합니다. 이 특성은 분 단위 장전 SLA와 맞지 않습니다.

### 결정

- 시간 민감한 scheduled AI Brief 실행은 **로컬 Docker 기반 scheduler를 primary**로 전환합니다.
- GitHub Actions는 다음 역할로 축소합니다.
  - CI/품질 검증
  - 수동 `workflow_dispatch`
  - scheduled fallback 또는 monitor
- Supabase는 계속 단일 운영 상태 저장소로 둡니다.
  - 리포트/인덱스 저장: Supabase Storage + `report_index`
  - 중복 실행 방지: `runtime_state` 기반 `market + session_date + run_type` idempotency
- 로컬 scheduler는 host scheduler(`launchd` 권장)가 one-shot Docker container를 실행하는 구조를 우선합니다.
  - container 내부 cron보다 host scheduler가 재부팅/로그/권한 관리가 명확합니다.
  - Docker container는 `sab scan -> sab entry -> sab ai-brief`를 한 번 수행하고, 최종 AI Brief artifact upload와 필수 Telegram schedule notification까지 처리한 뒤 종료합니다.
- 이 결정은 ADR-0005의 GitHub Actions + Supabase 자동화 결정을 **장전 AI Brief scheduled 실행에 한해 부분 대체**했습니다. 2026-07-06부터 Toss freshness-gated scheduled Sell AI Brief generation도 local generic wrapper 경로로 이 로컬 scheduled 실행 모델을 따릅니다. Scheduled scan workflow와 GitHub scheduled sell workflow는 현재 제공하지 않습니다.

### 목표

- 장전 AI Brief가 GitHub schedule 지연에 의해 PRE_OPEN window를 놓치는 재발 가능성을 낮춥니다.
- 같은 시장/세션 날짜에 AI Brief 리포트가 최대 1회만 생성되도록 합니다.
- Telegram 알림은 delivery-first 정책으로 운영하고, `runtime_state` marker로 정상 경로 중복을 방지합니다.
- 로컬 primary가 실패했을 때 운영자가 빠르게 알 수 있게 합니다.
- 현재 Supabase 중심 리포트 조회/웹 UI 구조는 유지합니다.

### 비목표

- 모든 scheduled workflow를 즉시 로컬로 이전하지 않습니다. Scheduled Sell AI Brief generation은 Toss freshness marker가 있을 때만 열려 있는 좁은 예외입니다.
- GitHub Actions를 제거하지 않습니다.
- 실시간/장중 AI Brief를 PRE_OPEN AI Brief의 fallback으로 취급하지 않습니다.
- 로컬 머신 장애를 완전히 제거하는 고가용성 시스템을 만들지 않습니다.

### 대안 검토

#### 대안 A: GitHub Actions 단일 cron을 더 앞당김

- 장점: 구현이 가장 작고 현재 구조를 거의 유지합니다.
- 단점: run 생성 지연/드롭이라는 근본 문제를 해결하지 못합니다.
- 판단: 단기 완화책으로는 가능하지만 primary 운영 설계로는 불충분합니다.

#### 대안 B: GitHub Actions 다중 cron + idempotency

- 장점: GitHub 안에서 재시도 확률을 올릴 수 있습니다.
- 단점: 같은 인프라 지연 특성을 공유하므로 분 단위 SLA를 보장하지 못합니다.
- 판단: local primary 이전 전 임시 완화 또는 fallback monitor로는 적합합니다.

#### 대안 C: 로컬 Docker primary + GitHub fallback

- 장점: schedule trigger를 GitHub 부하와 분리하고, 기존 Supabase/알림/CLI 계약을 재사용합니다.
- 단점: 로컬 Mac, Docker Desktop, 네트워크, 전원 상태에 의존합니다.
- 판단: 현재 개인 운용 환경에서는 시간 정확성과 구현 비용의 균형이 가장 좋습니다.

#### 대안 D: VPS/Fly.io/Render 같은 상시 서버 primary

- 장점: 로컬 머신 상태 의존도를 줄이고 서버형 운영에 가깝습니다.
- 단점: 비용, secret 운영, 고정 IP/네트워크 정책, 배포 경로가 추가됩니다.
- 판단: 로컬 primary가 불안정하다는 운영 증거가 쌓이면 승격할 후속 대안입니다.

### 결과/영향

- 장점
  - GitHub scheduled run 생성 지연에 직접 노출되지 않습니다.
  - Docker image/volume을 통해 로컬 캐시와 실행 환경을 더 일관되게 관리할 수 있습니다.
  - Supabase idempotency를 중심으로 로컬/GitHub fallback 중복 실행을 제어할 수 있습니다.
- 리스크/주의
  - Mac이 잠자기/종료 상태이면 primary가 실행되지 않습니다.
  - 로컬 secret 파일과 Docker 환경변수 관리가 운영 책임에 포함됩니다.
  - Docker Desktop 업데이트/로그인/daemon 상태가 실행 성공 조건이 됩니다.
  - fallback monitor가 없으면 로컬 실패를 장중 이후에야 알 수 있습니다.
- 완화책
  - `launchd` 작업에는 Wake/StartCalendarInterval과 실패 로그 경로를 명시합니다.
  - scheduler role window를 먼저 확인한 뒤 Docker daemon 상태를 확인하고, 유효한 role에서 실패하면 즉시 Telegram 알림을 보냅니다.
  - Supabase `runtime_state`에 lock/artifact/notification claim/notification sent/success marker를 기록해 중복 리포트와 정상 경로 중복 알림을 막습니다.
  - GitHub Actions는 "실행 주체"가 아니라 "missing report monitor/fallback" 역할로 유지합니다.

### 구현 계획

상세 구현 순서와 검증 기준은 [로컬 Docker scheduler 전환 계획](../local-docker-scheduler-plan.md)을 따릅니다.

### 후속 문서 갱신 기준

- 구현 전에는 `ARCHITECTURE.md`와 `runbook.md`의 현재 운영 설명을 바꾸지 않습니다.
- 로컬 scheduler가 실제 primary로 전환되면 다음 문서를 같은 PR에서 갱신합니다.
  - `docs/ARCHITECTURE.md`: scheduled AI Brief 실행 주체와 데이터 흐름
  - `docs/runbook.md`: launchd/Docker 운영, 로그 확인, 수동 재실행, 장애 대응
  - `.github/workflows/ai-brief.yml`: GitHub schedule 역할 축소 또는 monitor 전환
