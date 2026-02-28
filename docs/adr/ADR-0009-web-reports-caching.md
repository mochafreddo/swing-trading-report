## ADR-0009 — 웹 리포트 페이지 캐시: in-memory 2계층(서버 LRU + 클라이언트 dedupe)

상태: 채택(Accepted)  •  날짜: 2026-02-28

### 배경

- 현재 `/reports` UI는 초기 렌더(서버)와 상호작용(클라이언트) 모두에서 `/api/reports`, `/api/reports/detail`을 통해 Supabase(PostgREST + Storage)를 반복 조회합니다.
- 모든 경로가 `no-store`로 고정되어 있어, 같은 쿼리를 여러 번 수행해도 재사용이 거의 없습니다.
- 리포트 상세(Storage JSON)는 `x-upsert=false` 업로드 + duplicate index로 키 충돌 회피를 사용하므로, **키 단위로 사실상 불변(immutable)** 입니다.
  - 반면 리포트 목록(`report_index`)은 신규 리포트가 추가되며, 일부 필드(`summary/tickers_hydrated`)가 보강될 수 있어 **단기 최신성 요구**가 있습니다.

### 문제

- 동일 상세 리포트를 재선택/탭 전환 시마다 다운로드하여 I/O가 누적됩니다.
- 목록 조회도 쿼리 동일성(`type/q/limit`)이 유지되는 동안 반복 호출이 발생합니다.
- API 응답에 명시적 `Cache-Control`이 없어서, 호출자/플랫폼의 기본 동작에 의존합니다.

### 목표

- Supabase 읽기 호출을 **사용자 체감에 의미 있게** 줄인다(특히 상세 반복/목록 재조회).
- 최신성은 “몇 초 수준의 eventual consistency”로 타협하되, **상세는 키 단위 불변성**을 활용해 캐시 효율을 극대화한다.
- 브라우저/프록시의 디스크 기반 HTTP 캐시에 남지 않도록, 기본은 **in-memory 캐시**로 제한한다.
- 구현은 단순하게 유지하고(외부 인프라/Redis 없이), 테스트 가능해야 한다.

### 비목표

- 멀티유저/권한별 캐시 분리(현재 설계는 로컬 단일 사용자 운영이 기본).
- 실시간 무효화(웹훅/WS) 기반 “즉시 최신” 보장.
- 쓰기 경로(업로드/인덱스 upsert) 캐시.

### 결정

#### 1) 서버 캐시(인스턴스 단위)

- Node 런타임에서 **프로세스 메모리 LRU + TTL** 캐시를 둡니다.
- 적용 지점은 “Supabase 호출 직전”이 아니라, **도메인 단위 함수 경계**를 우선합니다.
  - `listReports({ type, q, limit, searchWindow })`
  - `readReportDetail(key)`
- 서버 캐시는 인증을 대체하지 않습니다.
  - API 라우트/페이지는 기존처럼 `requireAdminAuth`/`hasValidAdminSession`을 통과한 뒤에만 데이터를 사용합니다.

#### 2) 클라이언트 캐시(브라우저 세션 단위)

- UI 상호작용(리포트 선택/재선택)에서 중복 네트워크를 줄이기 위해 **in-memory dedupe/cache**를 둡니다.
- 외부 라이브러리 도입 여부는 구현 단계에서 결정합니다.
  - 옵션 A: `swr` 도입(`client-swr-dedup`).
  - 옵션 B: `useRef(new Map())` 기반의 최소 구현(의존성 추가 없음).

#### 3) 요청 단위 dedupe(서버 내부)

- 서버 렌더링/라우트 핸들러 내부에서 같은 호출이 중복될 수 있으므로, 필요 시 `React.cache()`로 **요청 단위 중복 제거**를 적용합니다(`server-cache-react`).

#### 4) API 응답 헤더

- 민감 데이터(리포트/보유) 성격을 고려해, `/api/reports*` 응답은 기본적으로 다음을 명시합니다.
  - `Cache-Control: private, no-store, max-age=0, must-revalidate`
- 성능은 HTTP 캐시가 아니라 1), 2)의 in-memory 캐시에서 확보합니다.

### 캐시 정책(초안)

#### 1) 리포트 상세(Storage JSON)

- 캐시 키: `report_detail:${bucket}:${key}`
- TTL: 1시간(조정 가능)
- LRU 최대 엔트리: 200 (조정 가능)
- 오류 캐시:
  - 404는 캐시하지 않거나 1초 이하의 매우 짧은 TTL만 허용(정리/보관기간 만료 시 “없음”이 즉시 반영되도록)
  - 5xx/네트워크 오류는 캐시하지 않음

#### 2) 리포트 목록(report_index)

- 캐시 키: `report_list:${type}:${limit}` (검색 없는 목록)
- TTL: 5초
- LRU 최대 엔트리: 50

#### 3) 티커 검색(`q` 포함)

- 캐시 키: `report_search:${type}:${q}:${limit}:${searchWindow}`
- TTL: 10초
- LRU 최대 엔트리: 100
- 주의: 검색은 `searchWindow` 내 페이지 순회가 비용이므로, “타이핑 중 반복 호출”을 완화하는 목적의 짧은 TTL만 둡니다.

### 무효화/최신성

- 신규 리포트 업로드는 **새로운 `report_key`** 를 생성하므로 상세 캐시는 무효화가 필요 없습니다.
- 목록/검색은 TTL 기반으로만 갱신합니다.
- (선택) 수동 갱신 수단:
  - `/api/reports?refresh=1` 또는 헤더 `x-sab-refresh: 1`로 캐시 바이패스/부분 무효화를 지원합니다.

### 보안 고려

- 캐시는 서버/클라이언트 모두 메모리에만 유지하며, 브라우저/프록시의 영속 HTTP 캐시는 금지(`no-store`)가 기본입니다.
- 인증/로컬 요청 가드는 캐시와 무관하게 항상 선행합니다.
- 캐시 모듈은 `server-only` 경계 내에서만 Supabase 시크릿을 다루며, 클라이언트로 절대 노출하지 않습니다.

### 구현 계획(요약)

- 서버
  - `web/src/lib/reports-data.ts` 경계에서 `listReports/readReportDetail`을 TTL/LRU로 감싼다.
  - 캐시는 `NODE_ENV=test`에서 기본 비활성화(테스트 간 오염 방지).
  - 필요 시 로그(히트/미스)는 `SAB_LOG_CACHE=1` 같은 플래그로 제한.
- 클라이언트
  - `web/src/components/reports/use-reports-state.ts`에서 리스트/상세 fetch를 dedupe/cache 한다.
  - focus revalidate는 기본 off(로컬 패널 UX에서 “갑자기 바뀌는 화면” 방지), 필요 시 수동 refresh 버튼 제공.
- 테스트
  - 서버 캐시 모듈에 단위 테스트를 추가해 TTL/바이패스/오류 정책을 고정한다.

### 구현 체크리스트(수용 기준)

- 서버
  - `listReports/readReportDetail`이 TTL/LRU 캐시를 사용하고, 동일 입력에 대한 Supabase 호출이 TTL 내 1회로 제한된다.
  - 인증/로컬 요청 가드 실패 시 캐시와 무관하게 401/403을 반환한다(캐시가 auth를 우회하지 않음).
  - `/api/reports*` 응답에 `Cache-Control: private, no-store, max-age=0, must-revalidate`가 항상 포함된다.
  - `refresh=1`(또는 `x-sab-refresh: 1`)에서 캐시 바이패스가 동작한다.
- 클라이언트
  - 같은 `selectedKey` 재선택 시 네트워크 재요청이 발생하지 않는다(세션 내).
  - 리스트/상세 요청이 중복 발화될 때 in-flight dedupe로 중복 요청이 합쳐진다.
- 테스트/품질
  - 캐시 모듈 단위 테스트로 TTL/바이패스/오류 캐시 정책이 고정된다.
  - 라우트 테스트로 `Cache-Control` 헤더가 회귀되지 않는다.

### 대안 검토

- Next.js fetch 캐시(`next: { revalidate }`/라우트 캐싱)만 사용
  - 장점: 프레임워크 표준
  - 단점: 인증/동적 라우트와의 상호작용이 복잡해지고, “브라우저 디스크 캐시 금지” 정책을 별도로 다뤄야 함
- 외부 캐시(Redis/Upstash)
  - 장점: 다중 인스턴스에서 일관된 캐시
  - 단점: 로컬 단일 사용자 범위에 과도한 운영 복잡도
