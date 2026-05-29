# ADR Index

상태: Archive

아키텍처 의사결정 기록(ADR) 인덱스입니다. 현재 기능 설명서가 아니라 의사결정 아카이브이므로, 최신 운영 계약은 [Spec v1.1](../spec-v1.1.md), [아키텍처](../ARCHITECTURE.md), [전략](../STRATEGY.md), [프로젝트 README](../../README.md)를 우선합니다.

- [ADR-0001 설정 우선순위: config.yaml → .env → CLI](ADR-0001-config-precedence.md) - 상태: Accepted (2025-11-06)
- [ADR-0002 리포트 아티팩트: JSON 단일 출력 + 로컬 대시보드](ADR-0002-report-artifacts-dashboard.md) - 상태: Accepted (2026-02-08)
- [ADR-0003 설정 충돌 정책: config.yaml / .env 중복 키 금지](ADR-0003-config-conflict-policy.md) - 상태: Accepted (2026-02-08)
- [ADR-0004 웹 스택: Next.js + 로컬 Docker 우선](ADR-0004-web-stack-nextjs-local-docker.md) - 상태: Accepted (2026-02-08)
- [ADR-0005 자동 실행: GitHub Actions 런너 + Supabase 저장소](ADR-0005-automation-github-actions-supabase.md) - 상태: Accepted (2026-02-08)
- [ADR-0006 v1.1 오픈 결정 정리](ADR-0006-open-decisions-v1.1.md) - 상태: Superseded (2026-02-23, ADR-0007로 대체)
- [ADR-0007 v1.1 현재 아키텍처 기준선(report_index/관리자 인증)](ADR-0007-v1.1-current-architecture-baseline.md) - 상태: Accepted (2026-02-23)
- [ADR-0008 Holdings 티커 입력 UX: 티커 디렉토리(캐시) + 검색/최근 후보](ADR-0008-holdings-ticker-directory.md) - 상태: Accepted (2026-02-28)
- [ADR-0009 웹 리포트 페이지 캐시: in-memory 2계층(서버 LRU + 클라이언트 dedupe)](ADR-0009-web-reports-caching.md) - 상태: Accepted (2026-02-28)
- [ADR-0010 Holdings 추가매수(Add Buy) 입력: Supabase RPC 원자 업데이트 + 평단 자동 재계산](ADR-0010-holdings-add-buy.md) - 상태: Accepted (2026-03-03)
- [ADR-0011 마켓 데이터 캐시 정책: adjusted 분리 + stale refresh + 미완성 캔들 방지](ADR-0011-market-data-cache-policy.md) - 상태: Accepted (2026-03-03)
- [ADR-0012 시간 민감 scheduled 실행: 로컬 Docker primary + GitHub fallback](ADR-0012-local-docker-scheduled-runs.md) - 상태: Accepted (2026-05-28)
