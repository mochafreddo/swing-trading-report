## ADR-0004 — 웹 스택: Next.js + 로컬 Docker 우선

상태: 채택(Accepted)  •  날짜: 2026-02-08

### 배경

- 개인용이지만 “웹에서 보기/검색/확장”하기 쉬운 UI가 필요합니다.
- VPS 비용은 당장 지출하지 않고, 맥북 로컬에서 Docker로 구동하는 형태를 우선합니다.
- 자동 실행은 노트북 상태에 의존하지 않도록(잠자기/종료), GitHub Actions 런너를 활용합니다.

### 결정

- 웹 UI는 **Next.js**로 구현한다.
- 기본 배포/실행은 **로컬 Docker(Compose)** 로 한다.
- `scan`/`sell` 실행은 웹에서 트리거할 수 있어야 하며(= GitHub Actions workflow dispatch), 자동 실행(스케줄러)일 때만 텔레그램/슬랙 알림을 보낸다.
- 보유 목록/리포트/실행 이력은 Supabase(Postgres/Storage)에 저장한다.

### 결과/영향

- 장점
  - UI/기능 확장이 쉽고, 장기적으로 배포 옵션(Vercel 등)도 열려 있습니다.
- 단점
  - 로컬 웹은 맥북이 켜져 있을 때만 접근 가능합니다(개인용 제약).
  - GitHub Actions / Supabase에 의존합니다(네트워크 필요).

### 관련 ADR

- ADR-0002: 리포트는 JSON 단일 아티팩트
