## ADR-0006 — v1.1 오픈 결정 정리(인덱스/캔들 캐시/인증)

상태: 대체됨(Superseded)  •  작성일: 2026-02-14  •  대체일: 2026-02-23

대체 ADR: `ADR-0007-v1.1-current-architecture-baseline.md`

> 참고: 본 ADR의 결정 중 #1 "인덱스 테이블 미도입"과 #3 "웹 UI 인증 미도입"은 현재 구현과 불일치하며,
> `ADR-0007-v1.1-current-architecture-baseline.md`에서 현행 아키텍처 기준으로 재정의되었습니다.
> 결정 #2 "캔들 캐시 미도입"은 ADR-0007에서도 그대로 유지되며(Supabase Postgres 캔들 캐시 테이블은 v1.1 범위에서 계속 미도입), 향후 확장 트리거(재검토 트리거 섹션)는 본 문서를 참조하세요.

### 배경

- v1.1은 “로컬 웹 + GitHub Actions 자동 실행 + Supabase 단일 저장소”를 최소 구성으로 완성한다.
- 성능/확장/보안 강화 항목은 필요가 명확해질 때 도입하는 편이 운영 리스크가 낮다.
- 따라서 v1.1에서 남아 있던 오픈 결정 3가지를 “도입/미도입(보류)”로 정리한다.

### 결정

1) 리포트 목록/검색(인덱스)

- v1.1에서는 **Supabase Storage listing**을 리포트 목록의 근거로 사용한다.
- 별도의 인덱스 테이블(`run_history` 등)은 **v1.1에 도입하지 않는다.**
- Run 상태/상세는 GitHub Actions 런 링크로 대체한다.

2) 캔들 캐시(속도/호출 수 절감)

- v1.1에서는 Supabase Postgres에 **캔들 캐시 테이블을 도입하지 않는다.**
- 로컬 `data/` 캐시는 “API 실패 시 폴백” 용도로만 유지한다.
- 호출 수/속도 문제가 생기면 다음 순서로 확장한다.
  - (우선) 로컬 캐시 기반 증분 갱신(최근 N일만 호출 후 병합)
  - (필요 시) GitHub Actions `actions/cache`로 `data/` 디렉터리 캐시
  - (그 다음) Supabase Postgres 캐시 도입 시 **JSONB-per-ticker**를 1차 후보로 검토한다(일봉만, 최근 N봉 유지)

3) 인증/권한(RLS)

- v1.1은 로컬 전용으로 운영하며, 웹 UI에 로그인/인증을 추가하지 않는다.
- Supabase 접근은 Next.js 서버(Route Handler/Server Action) 및 GitHub Actions에서만 수행한다(브라우저로 키 노출 금지).
- Postgres `holdings`는 RLS를 강제하고, `anon`/`authenticated` 권한은 제거해 서비스 키로만 접근한다.
- 공개 배포(Vercel 등)를 진행할 경우, 별도 ADR/SPEC에서 인증 방식(예: NextAuth, Supabase Auth)과 RLS 정책을 재결정한다.

### 결과/영향

- 장점
  - v1.1의 구현/운영 범위를 최소화하고, “동작하는 end-to-end”를 빠르게 유지한다.
  - 리포트 retention(기본 30일)로 listing 규모가 제한되어 인덱스 부재의 비용이 낮다.
- 단점/리스크
  - 리포트 수가 늘면 ticker 검색/필터가 느려질 수 있다(최근 N개 JSON 읽기 방식).
  - 캔들 호출 수가 많아지면 KIS rate limit 영향이 커질 수 있다.
  - 공개 배포 시 인증/권한 설계를 다시 해야 한다.

### 재검토 트리거(권장)

- 리포트 오브젝트 수가 수백~수천 단위로 증가하거나, ticker 검색이 체감상 느려짐
- scan/sell 실행이 반복적으로 rate limit/timeout에 걸림
- 공개 배포 또는 모바일 접근이 필요해짐
