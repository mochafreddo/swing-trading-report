# Docs Index

상태: Accepted (문서 인덱스)

이 디렉터리는 `swing-trading-report`의 현재 운영 문서, 계약 문서, 설계 기록, backlog, archive를 구분합니다. 처음 읽는 사람은 아래 `처음 읽는 순서`를 따르고, 과거 ADR/review 문서는 현재 source of truth로 사용하지 않습니다.

## 문서 상태

### 현재 제공

- 현재 동작 기준 문서를 역할별로 분리해 제공합니다.
- README는 짧은 진입점이고, 실무 절차는 아래 current 문서를 기준으로 합니다.

### 실험

- 별도 실험 문서 트리는 운영하지 않습니다.
- 전략/파라미터 실험은 코드, replay fixture, 테스트에서 추적하고 장기 유지가 필요할 때 정식 문서로 승격합니다.

### 백로그

- 미래 구현 범위와 제품 방향은 [Product Backlog](PRD.md)와 [Spec v1.3](spec-v1.3.md)에서 관리합니다.
- 웹 `Run` 탭과 GitHub Actions workflow의 standalone `entry` 전용 실행 경로는 backlog입니다.

### 폐기 후보

- owner 없이 남은 입력 포맷, 배포 옵션, 중복 스펙 문서는 즉시 삭제하지 않고 보관 후보로만 분류합니다.

## 처음 읽는 순서

| 순서 | 문서 | 목적 |
| ---: | --- | --- |
| 1 | [프로젝트 README](../README.md) | 프로젝트 개요, 빠른 시작, 문서 지도 |
| 2 | [Overview](overview.md) | 목적, 도메인 용어, 운영 흐름 |
| 3 | [Local Development](local-development.md) | 설치, 로컬 실행, 테스트, lint/build |
| 4 | [Configuration](configuration.md) | 환경변수와 config 파일 역할 |
| 5 | [Architecture](ARCHITECTURE.md) | 컴포넌트와 데이터 흐름 |
| 6 | [API](api.md) | CLI와 웹 API route 계약 |
| 7 | [Deployment](deployment.md) | Docker/GitHub Actions/Supabase 배포 |
| 8 | [Operations](operations.md) | 정기 운영, 로그, 헬스체크 |
| 9 | [Troubleshooting](troubleshooting.md) | 증상별 장애 대응 |
| 10 | [Contributing](contributing.md) | 커밋, PR, 검증 규칙 |

기존 `docs/runbook.md` 링크로 들어온 경우에는 [Runbook](runbook.md)을 호환 진입점으로 사용합니다. 새 운영 절차의 source of truth는 [Operations](operations.md), [Deployment](deployment.md), [Troubleshooting](troubleshooting.md)입니다.

## 현재 운영 기준

- [Overview](overview.md)
- [Local Development](local-development.md)
- [Configuration](configuration.md)
- [Architecture](ARCHITECTURE.md)
- [API](api.md)
- [Deployment](deployment.md)
- [Operations](operations.md)
- [Troubleshooting](troubleshooting.md)
- [Contributing](contributing.md)
- [Runbook 호환 진입점](runbook.md)
- [Swing 핵심 로직 설계](STRATEGY.md)
- [Spec v1.1 현재 계약](spec-v1.1.md)
- [KIS 설정 가이드](kis-setup.md)
- [holdings.yaml 스키마](holdings-schema.md)
- [config/env deep reference](config-reference.md)
- [main 브랜치 보호 운영 가이드](governance/main-branch-protection.md)

## 저장소 운영 문서

- [기여 가이드(root)](../CONTRIBUTING.md)
- [보안 정책](../SECURITY.md)
- [변경 이력](../CHANGELOG.md)
- [TODO](../TODOS.md)
- [에이전트 작업 지침](../AGENTS.md)
- [Codex Systematic Equities Team](codex-systematic-equities-team.md)

## 설계 기록

- [Holdings 추가매수 입력 설계](holdings-add-buy.md)
- [Holdings 티커 검색/선택 UX 설계](holdings-ticker-lookup.md)
- [로컬 Docker scheduler 전환 계획](local-docker-scheduler-plan.md)
- [AI Brief US source provider 결정 기록](ai-brief-us-source-provider-decision.md)

## backlog spec / roadmap

- [Product Backlog](PRD.md)
- [Spec v1.3 backlog 스펙](spec-v1.3.md)

## archive

- [ADR 인덱스](adr/README.md)
- [리뷰 인덱스](reviews/README.md)
- `docs/superpowers/plans/`는 agentic 작업 계획 artifact입니다.

## artifact

- `governance/*.json` 파일은 branch protection 적용 payload, snapshot, stage payload 같은 기계 아티팩트입니다.

## 문서 상태 기준

- `Accepted`: 현재 운영 기준이거나 구현 완료 설계 기록
- `Backlog`: 미래 구현 또는 제품 방향
- `Archive`: 과거 의사결정/리뷰 기록
- `Superseded`: 더 최신 ADR/문서로 대체된 기록
- `Artifact`: 도구 입력/출력에 가까운 비-Markdown 파일

## 네이밍 규칙

- 운영/how-to 문서: `docs/<topic>.md`
- ADR: `docs/adr/ADR-XXXX-<slug>.md`
- 리뷰: `docs/reviews/YYYY/review-YYYY-MM-DD.md`
- 버전 스펙/계획: `spec-vX.Y*.md`, `plan-vX.Y.md`
