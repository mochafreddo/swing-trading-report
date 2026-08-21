# Holdings Ticker Lookup 설계 (Web Console)

상태: Accepted (설계 기록)  
대상: `web`의 Holdings CRUD UX 개선 (기능 1, 2, 4 채택분)

## 문서 상태

### 현재 제공

- Holdings 입력 UX의 회사명/별칭 검색, 최근 buy 후보 패널, 티커 디렉토리 캐시 기반 검색 API는 현재 구현되어 있습니다.
- 관련 현재 동작은 `web/src/lib/ticker-directory.ts`, `/api/tickers/search`, `/api/tickers/recent-candidates`가 담당합니다.

### 실험

- 별도 experimental refresh UI는 현재 제공 범위에 포함하지 않습니다.

### 백로그

- 명시적 directory refresh 버튼과 추가 최적화는 backlog로 남아 있습니다.

### 폐기 후보

- 외부 전종목 심볼 검색 API를 붙여 ticker 규칙을 완화하는 방향은 채택하지 않습니다.

## 1) 문제

현재 Holdings 입력에서 US 종목은 `AAPL.NAS`처럼 **거래소 suffix가 포함된 티커**를 요구합니다.

- 사용자는 “코스트코/이튼/애브비” 같은 **회사명은 아는데**, `COST.NAS`, `ETN.NYS`, `ABBV.NYS` 같은 **정규 티커는 모르는 경우가 많음**
- `.NAS`, `.NYS` 같은 suffix까지 외워야 하고, 모르면 이전 스캔 리포트를 뒤져야 함
- 결과적으로 Holdings 입력 UX가 “검색/선택”이 아니라 “정답 맞히기” 형태가 됨

## 2) 목표 / 비목표

### 목표

- (F1) Holdings 입력에서 **회사명/별칭으로 검색**해서 티커를 **선택**하면 자동으로 `ticker` 필드가 채워진다.
- (F2) Holdings 화면에서 **최근 buy 스캔 후보 목록**을 바로 보고, 클릭 한 번으로 ticker를 채울 수 있다.
- (F4) 위 검색/후보 기능을 위해, 시스템이 점점 누적되는 **내부 ticker 디렉토리(캐시)**를 유지한다.
- 자동 채움 범위에서 **가격은 제외**한다(사용자가 본인 매입가를 입력).

### 비목표

- 외부(서드파티) “전종목 심볼 검색” API 연동(라이선스/품질/안정성/비용 이슈).
- ticker 규칙 완화(예: `AAPL`만 입력해도 저장) 또는 suffix 자동 추론(이건 별도 기능로 분리).
- holdings 테이블에 회사명 컬럼 추가(현재는 ticker만 단일 소스 유지).

## 3) UX 설계

### 3.1 Holdings Form: “티커 찾기” 입력 + 자동완성

- 기존 `Ticker` 입력은 유지하되, 바로 아래에 `티커 찾기(회사명/티커)` 입력을 추가한다.
- 사용자는 `코스트코` 또는 `ABBV`처럼 **기억나는 문자열**을 입력한다.
- 드롭다운으로 `(Ticker) (회사명)` 후보를 노출한다.
- 후보 클릭 시:
  - `form.ticker`를 canonical 티커(`COST.NAS`, `BRK.B.NYS`)로 채움
  - 선택된 후보를 **로컬 디렉토리에 “최근 선택”으로 기록**(F4)

검색 입력은 폼 저장과 무관한 “도우미”로 두어, 기존 검증/저장 흐름을 건드리지 않는다.

### 3.2 Holdings Form: “최근 buy 후보” 패널

- 폼 사이드바에 “최근 buy 후보” 섹션을 추가한다.
- 기본 동작:
  - 최근 `buy` 리포트 중 **candidate가 존재하는 가장 최신 리포트** 1건을 선택
  - 후보를 `(Ticker) (Name)` 형태로 최대 N개 표시하고, buy report `pattern`이 유효하면 함께 표시
  - 항목 클릭 시 `form.ticker`를 채우고, candidate `pattern`을 holdings `entry_pattern`으로 전달
  - “리포트 보기” 링크로 해당 리포트 상세 페이지 이동 가능

후보가 없으면:
- “최근 N개 buy 리포트에 후보가 없습니다.” 메시지 표시
- (선택) “이전 리포트 보기”로 최근 5개 키 선택 UI 제공

## 4) 데이터 설계: Ticker Directory Cache (F4)

### 4.1 저장 위치

- Supabase `runtime_state`에 단일 row로 저장한다.
  - `state_key = "ticker_directory:v1"`
  - `expires_at`는 충분히 크게(예: now + 365d) 설정하고, 갱신 시 연장한다.
- 이유: 별도 테이블 마이그레이션 없이, 기존 `runtime_state` 인프라/어댑터로 구현 가능.

### 4.2 디렉토리 엔트리 스키마 (제안)

```ts
export interface TickerDirectoryEntryV1 {
  ticker: string;              // canonical (e.g. COST.NAS, 005930)
  name?: string;               // buy report candidate.name (Korean, optional)
  aliases: string[];           // 검색 키워드(정규화 전/후 포함)
  lastSeenReportDate?: string; // YYYY-MM-DD
  lastSeenReportKey?: string;  // storage key
  selectedCount?: number;      // 사용자가 UI에서 선택한 횟수(선택)
  updatedAtMs: number;         // entry 단위 갱신 시각(정렬/우선순위에 사용)
}

export interface TickerDirectoryPayloadV1 {
  version: 1;
  builtAtMs: number;
  source: {
    buyReportsScanned: number;
    buyReportKeys: string[];        // 최근에 반영한 report keys (dedupe)
  };
  entries: TickerDirectoryEntryV1[];
}
```

### 4.3 aliases 생성 규칙(검색 UX)

- 기본 포함:
  - `ticker` 전체(`COST.NAS`)
  - US일 경우 base symbol(`COST`)
  - class ticker의 경우 slash/dot alias(`BRK.B.NYS`, `BRK/B.NYS`)
  - `name` 원문(공백 포함) + 공백 제거 버전(`"코스트코 홀세일"`, `"코스트코홀세일"`)
- 정규화:
  - 대소문자 무시
  - 연속 공백/특수문자 제거한 검색 문자열을 별도로 생성해 매칭

영문 회사명(예: “AbbVie”)까지 완벽히 커버하는 것은 비목표로 둔다. 단, ticker(`ABBV`) 검색은 지원하므로 현실적으로 커버 범위는 충분하다.

### 4.4 빌드/갱신 알고리즘

- 입력 소스(우선순위):
  1. 최근 buy 리포트(candidates 배열에서 `ticker`, `name` 추출)
  2. 사용자의 UI 선택 로그(선택 count/최근 선택)
- 갱신 트리거:
  - `/api/tickers/search` 요청 시 디렉토리가 없거나 stale이면 백그라운드/동기 refresh
  - Holdings 페이지 로드시 명시 refresh 호출(선택)
  - 사용자 “Refresh directory” 버튼(선택)
- stale 기준(제안):
  - `builtAtMs`가 24h 초과
  - 또는 report_index 최신 buy report key가 payload.source.buyReportKeys에 없음

갱신은 “전체 재빌드”보다 **incremental**이 우선:
- report_index에서 최신 buy report keys를 가져오고,
- payload에 반영되지 않은 key만 storage에서 내려받아 merge.

## 5) API 설계 (Web)

### 5.1 `GET /api/tickers/search?q=...`

- 목적: 회사명/별칭/티커 substring 기반 자동완성 후보 제공
- 입력:
  - `q`: string (trim, min 1)
  - `limit`: number (optional, default 20, max 50)
- 출력:

```json
{
  "q": "코스트코",
  "results": [
    { "ticker": "COST.NAS", "name": "코스트코 홀세일", "reason": "name_match" }
  ],
  "directory": { "builtAtMs": 0, "sourceReports": 0 }
}
```

- 보안: 기존 holdings/reports API와 동일하게 `requireAdminAuth` + `same-origin` + `local-request` 적용

검색은 서버에서 수행하고, 클라이언트는 결과만 렌더링한다.

### 5.2 `GET /api/tickers/recent-candidates`

- 목적: “최근 buy 후보” 패널 데이터 제공
- 입력:
  - `limitReports`: default 10
  - `limitCandidates`: default 50
- 동작:
  - 최근 buy 리포트들을 확인하고 candidates가 비어있지 않은 첫 리포트를 선택
  - 해당 report의 candidates에서 `{ticker, name, pattern}`을 추출해 반환
  - `pattern`은 holdings storage allowlist(`trend_pullback_bounce`, `swing_high_breakout`, `rsi_oversold_reversal`)와 일치할 때만 문자열로 반환하고, 누락/invalid 값은 `null`로 정규화합니다.

주의: ticker directory cache/search 계약은 계속 `{ticker, name}` 중심입니다. `pattern`은 최근 후보 선택 UX에서 최신 buy report를 직접 읽을 때만 전달하며, 검색 캐시에 저장하지 않습니다.

### 5.3 `POST /api/tickers/directory/refresh` (선택)

- 목적: 사용자가 명시적으로 디렉토리 갱신을 트리거
- 출력:
  - 갱신 후 metadata(`builtAtMs`, 반영 report 수, entry 수)

## 6) 서버 구현 위치 (제안)

- API 라우트:
  - `web/src/app/api/tickers/search/route.ts`
  - `web/src/app/api/tickers/recent-candidates/route.ts`
  - (선택) `web/src/app/api/tickers/directory/refresh/route.ts`
- 디렉토리 모듈(server-only):
  - `web/src/lib/ticker-directory.ts`
    - `loadDirectory()`
    - `refreshDirectoryIfNeeded()`
    - `searchDirectory(q, limit)`
    - `extractCandidatesFromBuyReport(reportJson)`
- Supabase 접근:
  - `fetchReportIndexPage` + `downloadStorageJson` 재사용
  - `fetchRuntimeStateEntry` + `upsertRuntimeStateEntry` 재사용

## 7) 테스트/검증(구현 단계)

- 유닛 테스트(권장)
  - buy report JSON에서 candidates 추출 회귀 테스트(스키마 드리프트 내구성)
  - aliases 생성(특히 class ticker의 `BRK/B.NYS` 처리) 테스트
  - 검색 랭킹(정확한 ticker 매치 > name 매치 > 부분 매치) 테스트
- API 라우트 테스트
  - auth/guard 경계(`AdminAuth`, `same-origin`, `local-request`)
  - 빈 디렉토리/리포트 없음/후보 없음 처리

## 8) 단계적 롤아웃

1. 서버 디렉토리 + `/api/tickers/search` 구현 완료
2. Holdings Form “티커 찾기” 입력 + 자동완성 UI 연결 완료
3. `/api/tickers/recent-candidates` + “최근 buy 후보” 패널 추가 완료
4. 디렉토리 갱신 최적화(incremental, stale 감지) + “최근 선택” 반영은 backlog
