## ADR-0002 — 리포트 아티팩트: JSON 단일 출력 + 로컬 대시보드

상태: 채택(Accepted, Amended 2026-05-23)  •  날짜: 2026-02-08

### 배경

- 기존은 마크다운(`.md`) 리포트가 1차 산출물이었지만, 웹에서 보기 편한 UX를 만들려면 **구조화된 데이터**가 필요합니다.
- “하나만 보면 되게” 유지하려면, 사람이 읽는 출력과 프로그램이 소비하는 출력이 이중화되지 않는 편이 좋습니다.

### 결정

- `sab scan` / `sab sell`의 **정식 산출물은 JSON 아티팩트**로 한다.
  - Buy: `YYYY-MM-DD.buy.json`
  - Sell: `YYYY-MM-DD.sell.json`
  - 같은 날 여러 번 생성 시: `YYYY-MM-DD-1.buy.json` 처럼 suffix로 충돌 회피
- JSON 스키마는 상단에 버전 문자열을 둔다.
  - `schema: "sab.report.v1"`
  - `type: "buy" | "sell"`
- JSON 아티팩트는 다음 위치 중 하나(또는 둘 다)에 저장될 수 있다.
  - 로컬 파일: `reports/` 디렉터리(개발/디버그)
  - 원격 보관: Supabase Storage(개인용 단일 소스)
- 로컬 웹 UI는 Supabase(또는 로컬 파일)의 JSON 아티팩트를 읽어 렌더링한다. (웹 스택은 ADR-0004 참고)
- 마크다운 리포트는 정식 출력이 아니며(기본 비활성/제거 방향), 필요해지면 “내보내기(export)”로만 재검토한다.

### 후속 변경(Amendment, 2026-05-23)

본 ADR 채택 이후 JSON 단일 출력 + 로컬 대시보드 규약을 따르는 두 종류의 run이 추가되어 현재 production set은 4종이다.

- Storage/report_index run type: `buy | sell | entry | ai-brief` (`sab/report/storage_key.py:6` `_ALLOWED_RUN_TYPES`가 source of truth)
- 추가 명령
  - `sab entry`: `YYYY-MM-DD.entry.json` (`sab/report/entry_report.py`)
  - `sab ai-brief`: `YYYY-MM-DD.ai-brief.json` (`sab/report/ai_brief_report.py`)
- `buy`/`sell`/`entry` report schema는 `"sab.report.v1"` 계열을 유지하고, AI Brief artifact는 `schema="sab.ai_brief.v1"` / `type="ai_brief"`를 사용한다. Storage key와 `report_index.type`의 run type만 `ai-brief`로 표준화하며, 본 결정의 골격(JSON 단일 출력 + 로컬 대시보드)은 변경 없이 유지된다.

### 결과/영향

- 장점
  - UI 구현이 단순해지고(파싱 불필요), 필터/검색/정렬 등 탐색 기능 확장이 쉬워집니다.
  - 리포트 구조가 명시돼 테스트/회귀 고정이 쉬워집니다.
- 단점
  - 사람이 바로 읽으려면 대시보드(또는 JSON 뷰어)가 필요합니다.
  - 스키마 변경 시 하위호환 정책을 고려해야 합니다.

### 대안 검토

- Markdown만 유지: 사람이 읽기 쉽지만 UI/자동화에 불리
- Markdown + JSON 이중 산출: 호환성은 좋지만 유지보수 비용/드리프트 위험 증가
- SQLite 단일 DB: 확장성은 좋지만 초기 복잡도 증가
