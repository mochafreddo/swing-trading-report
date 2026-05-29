# Docs Index

상태: Accepted (문서 인덱스)

`docs/`의 공식 진입점입니다. 현재 운영 기준 문서, 설계 기록, backlog spec, archive, artifact를 아래 역할로 구분합니다.

## 어디서부터 읽을까 (Where to start)

처음 오셨다면 목적에 맞는 문서부터 보세요. 세부 문서는 아래 분류에서 찾을 수 있습니다.

| 목적 | 먼저 볼 문서 |
| --- | --- |
| 프로젝트가 무엇인지 / 빠른 시작 / CLI·웹 실행 | [프로젝트 README](../README.md) |
| 로컬 개발 환경·품질 검증·커밋 규칙 | [기여 가이드](../CONTRIBUTING.md) |
| 실행·디버그·장애 대응(운영) | [런북](runbook.md) |
| 시스템 구조·컴포넌트·데이터 흐름 | [아키텍처](ARCHITECTURE.md) |
| 신호/리스크 전략 로직 | [전략](STRATEGY.md) |
| 환경변수·시크릿 설정 | [`.env.example`](../.env.example), [보안 정책](../SECURITY.md) |
| KIS 데이터 연동 설정 | [KIS 설정 가이드](kis-setup.md) |
| 현재 저장소 계약(스토리지/인덱스/런타임 상태) | [Spec v1.1](spec-v1.1.md) |

## 문서 상태

### 현재 제공

- 현재 동작/운영 기준은 [`README`](../README.md), [런북](runbook.md), [아키텍처](ARCHITECTURE.md), [전략](STRATEGY.md), [Spec v1.1](spec-v1.1.md), setup/schema 가이드를 우선합니다.
- 구현이 끝난 기능 설계는 `Accepted` 상태의 설계 기록으로 유지합니다.

### 실험

- 별도 실험 전용 문서 트리는 두지 않습니다.
- 파라미터/가설 실험은 코드, replay fixture, 리뷰 문서에서 추적하고 장기 유지가 필요해지면 정식 문서로 승격합니다.

### 백로그

- 미래 구현 범위와 제품 비전은 [PRD](PRD.md)와 [Spec v1.3](spec-v1.3.md)에서 관리합니다.
- 운영 문서에 남은 vague한 "예정" 항목은 별도 backlog 문서로 이동하는 것을 원칙으로 합니다.

### 폐기 후보

- owner 없이 남은 새 입력 포맷, 배포 옵션, 중복 스펙 문서는 backlog로 승격하지 않고 폐기 후보로 둡니다.

## 현재 운영 기준

- [프로젝트 README](../README.md)
- [런북](runbook.md)
- [시스템 아키텍처 개요](ARCHITECTURE.md)
- [Swing 핵심 로직 설계(신호/리스크)](STRATEGY.md)
- [AI Brief US source provider 결정 기록](ai-brief-us-source-provider-decision.md)
- [Spec v1.1 현재 계약](spec-v1.1.md)
- [KIS 설정 가이드](kis-setup.md)
- [holdings.yaml 스키마](holdings-schema.md)
- [main 브랜치 보호 운영 가이드](governance/main-branch-protection.md)
- [Codex Systematic Equities Team](codex-systematic-equities-team.md)

## 저장소 운영 문서

- [기여 가이드](../CONTRIBUTING.md)
- [보안 정책](../SECURITY.md)
- [변경 이력](../CHANGELOG.md)
- [TODO](../TODOS.md)
- [에이전트 작업 지침](../AGENTS.md)

## 설계 기록

- [Holdings 추가매수 입력 설계](holdings-add-buy.md)
- [Holdings 티커 검색/선택 UX 설계](holdings-ticker-lookup.md)

## backlog spec / roadmap

- [PRD](PRD.md)
- [Spec v1.3 backlog 스펙](spec-v1.3.md)
- [로컬 Docker scheduler 전환 계획](local-docker-scheduler-plan.md)

## archive

- [ADR 인덱스](adr/README.md)
- [리뷰 인덱스](reviews/README.md)

## artifact

- `governance/*.json` 파일은 적용 payload, current snapshot, stage payload 같은 기계 아티팩트입니다.

## 문서 상태 기준

- `Accepted`: 현재 운영 기준이거나, 구현이 끝난 설계 기록
- `Backlog`: 미래 구현 또는 제품 비전/로드맵
- `Archive`: 과거 의사결정/리뷰 기록
- `Artifact`: 도구 입력/출력에 가까운 비-Markdown 파일 분류
- `Superseded`: 더 최신 ADR/문서로 대체된 기록
- 새 Markdown 문서는 커밋 전에 `Accepted`, `Backlog`, `Archive`, `Superseded` 중 하나로 정규화합니다.

## 네이밍 규칙

- ADR: `docs/adr/ADR-XXXX-<slug>.md`
- 리뷰: `docs/reviews/YYYY/review-YYYY-MM-DD.md`
- 버전 스펙/계획: `spec-vX.Y*.md`, `plan-vX.Y.md`
- 운영 전환 계획: `docs/<topic>-plan.md`
