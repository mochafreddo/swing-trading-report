# v1.2 백로그 스펙 — Holdings Import/Export

상태: Backlog (v1.2)  
작성일: 2026-02-14

## 1) 목적

- v1.1은 `holdings` 단일 소스(Postgres) + 웹 CRUD를 유지한다.
- v1.2에서 초기 이관/백업 편의를 위해 `holdings.yaml` import/export를 추가한다.
- v1.2 도입 전까지 공개 API는 변경하지 않는다(`v1.1 유지`).

## 2) 범위 / 비범위

### 범위(In)

- 서버 API
  - `GET /api/holdings/export?format=yaml`
  - `POST /api/holdings/import?mode=upsert&dry_run=true|false`
- 포맷: `docs/holdings-schema.md`의 `version: 1` + `holdings[]`만 지원
- 단일 사용자(로컬 운영) 기준의 안전한 이관/백업

### 비범위(Out)

- CSV/XLSX import/export
- 삭제 동기화(파일에 없는 DB row 자동 삭제)
- 멀티유저 권한/워크스페이스 단위 정책

## 3) 데이터 계약

### 3.1 Export 결과 YAML

루트는 아래 두 필드만 사용한다.

```yaml
version: 1
holdings:
  - ticker: AAPL.US
    quantity: 3
    entry_price: 172.5
    entry_currency: USD
    entry_date: 2024-10-11
    strategy: swing
    notes: sample
    tags: [core, us]
    stop_override: null
    target_override: null
```

- 출력 필드: `ticker`, `quantity`, `entry_price`, `entry_currency`, `entry_date`, `strategy`, `notes`, `tags`, `stop_override`, `target_override`
- 비출력 필드: `created_at`, `updated_at`
- 정렬: `ticker` 오름차순(결정적 백업 결과 보장)

### 3.2 Import 입력 YAML

- 허용 루트 키: `version`, `holdings`
- `version`은 `1`만 허용
- `holdings`는 배열 필수(빈 배열 허용)
- `settings` 포함 기타 루트 키는 거부(명시적 에러)

## 4) API 계약

### 4.1 `GET /api/holdings/export?format=yaml`

- Query
  - `format`: 필수, `yaml`만 허용
- Response
  - `200 OK`
  - `Content-Type: text/yaml; charset=utf-8`
  - `Content-Disposition: attachment; filename="holdings-YYYYMMDD.yaml"`
  - Body: 3.1 계약의 YAML 텍스트
- Error
  - `400`: 지원하지 않는 `format`
  - `500`: Supabase 조회/직렬화 실패

### 4.2 `POST /api/holdings/import?mode=upsert&dry_run=true|false`

- Query
  - `mode`: 기본값 `upsert`, 현재 `upsert`만 허용
  - `dry_run`: 기본값 `true`
- Request
  - `Content-Type: multipart/form-data`
  - 파일 필드명: `file`
  - 파일 인코딩: UTF-8 YAML
- Response (`200 OK`)
  - JSON
  - `dry_run`, `mode`, `summary`, `errors`를 포함
  - 예시:

```json
{
  "dry_run": true,
  "mode": "upsert",
  "summary": {
    "total": 3,
    "valid": 3,
    "created": 1,
    "updated": 2,
    "unchanged": 0
  },
  "errors": []
}
```

- Error
  - `400`: 파일 누락, 잘못된 query 값, YAML 파싱 실패, 스키마 검증 실패
  - `409`: 파일 내 duplicate ticker
  - `500`: Supabase 업서트 실패

## 5) Import 처리 규칙

- ticker 정규화: trim + uppercase
- 필수 필드: `ticker`, `quantity`, `entry_price`
- 선택 필드 기본값
  - `entry_currency`, `entry_date`, `strategy`, `notes`, `stop_override`, `target_override`: `null`
  - `tags`: `[]`
- 검증 실패가 1건이라도 있으면 전체 요청을 실패 처리한다(부분 반영 금지).
- `dry_run=true`에서는 DB 쓰기를 절대 수행하지 않는다.
- `dry_run=false`에서는 bulk upsert 1회로 반영한다.
- 파일에 없는 DB row는 유지한다(삭제 동기화 비활성).

## 6) 구현 순서 (v1.2)

1. `web/src/lib/holdings-transfer.ts`
   - YAML 파싱/검증/정규화
   - DB row -> YAML 직렬화
   - 요약(summary) 계산 유틸
2. `web/src/lib/supabase-admin.ts`
   - `fetchHoldingsTickers()` 추가(생성/수정/무변경 계산용)
   - `upsertHoldingsBulk()` 추가(배열 단위 upsert)
3. `web/src/app/api/holdings/export/route.ts`
   - `format=yaml` 검증
   - holdings 조회 + YAML 응답
4. `web/src/app/api/holdings/import/route.ts`
   - multipart 파일 수신
   - query 검증(`mode`, `dry_run`)
   - dry-run / apply 분기
5. `web/src/components/holdings-client.tsx`
   - Export 버튼(다운로드)
   - Import 파일 선택 + 결과(요약/에러) 표시
   - 기본 플로우: dry-run 결과 확인 후 apply 버튼으로 반영

## 7) 테스트 시나리오

### 7.1 단위 테스트

- YAML 파싱/직렬화 정상 케이스
- 필수 필드 누락 실패
- 잘못된 숫자(`quantity`, `entry_price`) 실패
- 잘못된 날짜(`entry_date`) 실패
- duplicate ticker 실패
- `settings`/알 수 없는 루트 키 실패

### 7.2 API 테스트

- `GET /api/holdings/export?format=yaml` 200 + 헤더/본문 검증
- `GET /api/holdings/export?format=json` 400
- `POST import` + `dry_run=true`에서 DB 무반영 보장
- `POST import` + `dry_run=false`에서 upsert 반영 보장
- `mode` 미지정 시 `upsert` 기본값 적용
- `mode=replace` 등 미지원 값 400

### 7.3 회귀 테스트

- 기존 `GET/POST /api/holdings`, `PATCH/DELETE /api/holdings/[ticker]` 동작 불변
- Holdings UI CRUD 경로 불변
- 시크릿 경계 테스트(클라이언트 번들에 서버 키 미노출) 유지

## 8) 기본 가정/디폴트

- 단일 사용자 로컬 운영
- import 기본 모드: `upsert`
- `dry_run` 기본값: `true`(안전 우선)
- 삭제 동기화 기본 비활성(명시 옵션 없는 한 수행하지 않음)
