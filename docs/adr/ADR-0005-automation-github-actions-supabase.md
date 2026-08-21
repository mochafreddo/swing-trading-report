## ADR-0005 — 자동 실행: GitHub Actions 런너 + Supabase 저장소

상태: 채택(Accepted)  •  날짜: 2026-02-08

### 배경

- 맥북은 잠자기/종료가 있어 자동 실행을 로컬에만 의존하기 어렵습니다.
- 개인용이라도 보유 목록/리포트/실행 이력은 “상시 접근 가능한 단일 저장소”가 필요합니다.

### 결정

- `scan`/`sell` GitHub Actions workflow는 현재 manual-only `workflow_dispatch`로 운영한다.
- scheduled `scan`과 GitHub scheduled `sell`은 marker-aware fallback 설계 전까지 fail closed로 두며, GitHub schedule 전용 Telegram/Slack 요약 알림도 제공하지 않는다.
- 실행 결과(리포트/이력/보유 목록)는 **Supabase(Postgres/Storage)** 를 단일 소스로 저장한다.
- 요약 알림은 명시적으로 지원되는 수동/스케줄 경로에서만 전송한다.
- 워크플로우 실패/에러 알림은 GitHub Actions 기본 알림(Notifications/메일/모바일 푸시)으로 수신한다.

### 결과/영향

- 장점
  - 노트북 상태와 무관하게 자동 실행 가능
  - 로컬 웹(Next.js)은 Supabase를 통해 언제든 동일 데이터를 조회 가능
- 리스크/주의
  - KIS API가 IP 제한/정책을 요구하면 GitHub Actions 환경에서 실패할 수 있음
    - 이 경우 고정 IP 환경(VPS 등)으로 전환이 필요할 수 있음
  - 런너가 매 실행마다 초기 상태이므로, 토큰/캐시(호출 수 절감)는 Supabase에 저장하거나 별도 캐시 전략이 필요

### 후속 결정

- 2026-05-28 [ADR-0012](ADR-0012-local-docker-scheduled-runs.md)가 시간 민감한 장전 AI Brief scheduled 실행에 한해 이 결정을 부분 대체했습니다.
- 2026-07-06 로컬 scheduled Sell AI Brief generation은 Toss freshness marker를 전제로 하는 local generic wrapper 경로로 추가되었고, GitHub `sell.yml`은 계속 manual-only로 둡니다.
- `scan`/`sell`은 별도 ADR 전까지 GitHub Actions + Supabase 구조를 유지하되, workflow trigger는 manual-only로 둡니다.
