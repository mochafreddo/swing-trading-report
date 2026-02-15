# Security Best Practices Review (로컬 1인 사용 전제)

작성일: 2026-02-15

## Executive summary

- Python CLI(`sab`) 쪽은 **시크릿을 YAML에 두지 못하게 차단**하고(`sab/config.py:159-166`), YAML 파싱도 `safe_load`만 사용하며(`sab/config_loader.py:38-53`, `sab/holdings_loader.py:67-83), KIS 토큰 캐시는 원자적으로 저장합니다(`sab/data/kis_client.py:275-285`, `sab/utils/atomic_io.py:32-62`).
- 반면 Next.js 웹은 기본 실행/도커 포트 바인딩이 **로컬 전용을 강제하지 않습니다**(`docker-compose.yml:10-15`, `web/package.json:7-9`). 여기에 `/api/run`·`/api/reports*`는 인증/로컬 제한이 없어, LAN 등에 노출되면 **Supabase 데이터 접근** 및 **GitHub Actions 트리거**가 가능합니다(`web/src/app/api/run/route.ts:11-41`, `web/src/app/api/reports/route.ts:36-113`).
- “내 PC에서만 접근(127.0.0.1)”이 정말 전제라면, 웹 런타임도 그 전제에 맞게 **포트 바인딩/가드 범위를 조정**하는 것이 핵심입니다.

## Scope / Assumptions

- 단일 사용자, 로컬에서만 사용(공개 서비스/다중 사용자/인터넷 노출 아님).
- 다만 아래 시크릿은 “로컬이라도” 유출 시 영향이 큽니다.
  - `GITHUB_PAT`(워크플로 디스패치), `SUPABASE_SECRET_KEY`/`SUPABASE_SERVICE_ROLE_KEY`(DB/Storage 관리자 권한), `KIS_APP_SECRET`(증권 API).

---

## Findings

### SBP-001 — 웹 컨테이너가 모든 인터페이스로 노출 + 무인증 API 존재 (로컬 전제 불일치)

- Severity: **High (로컬/호스트 외부에서 접근 가능해지는 순간)**
- Location:
  - `docker-compose.yml:6-15` (포트 바인딩/`.env` 주입)
  - `web/package.json:7-9` (Next dev/start가 `0.0.0.0` 바인딩)
  - `web/src/app/api/run/route.ts:11-41` (무인증 GitHub Actions 디스패치)
  - `web/src/app/api/reports/route.ts:36-113` + `web/src/app/api/reports/detail/route.ts:13-45` (무인증 리포트 열람)
- Evidence:
  - 도커 포트가 `${WEB_HOST_PORT}:3000` 형태로 바인딩되어, Docker 기본 동작상 호스트의 `0.0.0.0:${WEB_HOST_PORT}`로 열릴 수 있습니다(`docker-compose.yml:10-11`).
  - `/api/run`은 요청자 확인 없이 PAT로 GitHub API를 호출합니다(`web/src/lib/github-actions.ts:58-74`).
  - `/api/reports*`는 Supabase secret/service-role 키로 Storage JSON을 내려받아 그대로 반환합니다(`web/src/lib/supabase-admin.ts:157-190`).
- Impact:
  - 같은 네트워크(회사/카페/가정 LAN)에서 포트에 접근할 수 있는 타인이 `/api/run`을 호출하면, 본인 계정 권한(PAT)으로 워크플로를 실행시킬 수 있습니다.
  - `/api/reports*`를 통해 리포트가 외부로 유출될 수 있습니다(전략/보유/메타데이터 등).
- Recommended fix (로컬 전제에 가장 맞는 순서):
  1. **호스트 포트 바인딩을 loopback으로 제한**: `127.0.0.1:${WEB_HOST_PORT}:3000` 형태로만 열리게 구성(Compose 레벨에서 강제).
  2. `/api/run`, `/api/reports*`도 `/api/holdings*`처럼 **로컬 요청만 허용**하거나(가드 재사용), LAN 접근이 필요하면 **인증 경계(공유 시크릿/Basic Auth 등)**를 추가.
  3. (방어 심화) GitHub Actions 디스패치에 사용되는 `ref`를 **고정(main) 또는 allowlist**로 제한(SBP-003 참고).
- Mitigation / Notes:
  - “브라우저로만 접근”을 가정해도 `/api/run`·`/api/reports*`는 호스트/IP로 직접 호출이 가능해 공격 표면이 큽니다.
  - OS 방화벽/라우터 설정이 외부 접근을 막고 있다면 위험은 낮아지지만, 구성 변경/환경 변화에 취약합니다.

---

### SBP-002 — `assertLocalRequest`가 Host 헤더 기반 (방어로는 유효하나 보안 경계로는 불완전)

- Severity: **Medium (포트 노출 시), Low (loopback 바인딩 시)**
- Location: `web/src/lib/local-request-guard.ts:56-62`
- Evidence:
  - 로컬 여부 판단이 `x-forwarded-host` 또는 `host` 헤더의 hostname만으로 이루어집니다.
- Impact:
  - 비브라우저 클라이언트는 `Host: localhost` 같은 헤더를 임의로 넣을 수 있어, “네트워크로 접근 가능”한 상황에서는 우회 가능성이 있습니다.
  - 반대로, DNS Rebinding류(브라우저 기반)에는 Host allowlist가 도움이 됩니다(브라우저는 Host를 임의 지정하기 어렵기 때문).
- Recommended fix:
  - 로컬 전제라면 **우선순위는 포트 loopback 바인딩**(SBP-001)입니다.
  - LAN 접근을 의도한다면 Host 헤더가 아니라 **명시적 인증(공유 시크릿/세션)**로 경계를 만드세요.

---

### SBP-003 — `/api/run`의 `ref` 오버라이드가 허용됨 (워크플로 실행 대상을 고정하지 않음)

- Severity: **High (웹이 외부에서 호출 가능해지는 경우), Medium (로컬 단독 사용)**
- Location:
  - 입력 스키마: `web/src/lib/schemas.ts:146-164`
  - ref 적용: `web/src/lib/github-actions.ts:33-55`
  - 엔드포인트(무가드): `web/src/app/api/run/route.ts:11-41`
- Evidence:
  - `ref`가 optional string으로 허용되고(`schemas.ts:146`), 디스패치 body에 그대로 들어갑니다(`github-actions.ts:34`, `github-actions.ts:51-54`).
- Impact:
  - 공격자가 `/api/run`을 호출할 수 있는 상황에서, `ref`를 임의로 지정해 워크플로를 실행하게 만들 수 있습니다.
  - GitHub Actions 워크플로는 시크릿을 사용하므로(`.github/workflows/scan.yml:42-49`, `.github/workflows/sell.yml:33-40`), “실행되는 ref의 코드”가 바뀌면 시크릿 유출 위험이 커집니다.
- Recommended fix:
  - 로컬 전제라면 가장 간단히 **`ref` 입력을 제거하고 항상 `"main"` 고정**.
  - 또는 allowlist(예: `main`/`release/*` 등)로 제한하고, `refs/pull/*` 같은 형태는 차단.

---

### SBP-004 — 웹 컨테이너에 불필요한 시크릿(KIS 등)까지 주입됨 (권한 최소화 미흡)

- Severity: **Low~Medium (노출/취약점 발생 시 영향 확대)**
- Location: `docker-compose.yml:6-9`, `.env.example:10-21`
- Evidence:
  - 웹 컨테이너가 `.env` 전체를 로드합니다(`docker-compose.yml:6-7`).
  - `.env`에는 KIS 시크릿도 포함됩니다(`.env.example:10-12`).
- Impact:
  - 웹 서버가 어떤 이유로든 침해/디버그/에러 노출되면, “웹이 실제로 필요 없는” 시크릿까지 같이 위험해집니다.
- Recommended fix:
  - `.env.web`(Supabase/GitHub 관련만)과 `.env.cli`(KIS 포함)로 분리하거나,
  - compose의 `environment:`에 웹에 필요한 키만 명시적으로 전달.

---

### SBP-005 — Dockerfile에서 pnpm을 `curl`로 직접 내려받아 설치 (무결성 검증 없음)

- Severity: **Low (개인용), 공급망 관점에서는 Medium**
- Location: `web/Dockerfile:4-7`
- Evidence:
  - GitHub release 바이너리를 checksum/서명 확인 없이 다운로드해 실행합니다.
- Impact:
  - 네트워크/다운로드 경로가 공격받으면 빌드 단계에서 악성 바이너리가 실행될 수 있습니다.
- Recommended fix:
  - Node의 `corepack` 기반으로 pnpm을 활성화(버전은 `package.json:5`의 `packageManager`를 따르게)하거나,
  - 최소한 checksum 검증을 추가.

---

### SBP-006 — GitHub Actions가 태그(v4/v5/v7)로만 고정됨 (SHA pinning 미적용)

- Severity: **Low (개인용), 공급망 관점에서는 Medium**
- Location: 예) `./.github/workflows/deps-upgrade.yml:28-35`, `./.github/workflows/deps-upgrade.yml:51-61`
- Evidence:
  - `actions/checkout@v4`, `actions/setup-python@v5`, `peter-evans/create-pull-request@v7` 등 태그 사용.
- Impact:
  - 액션 공급망 이슈가 발생하면 워크플로 실행이 영향을 받을 수 있습니다.
- Recommended fix:
  - 가능하면 **커밋 SHA로 pinning**(특히 `peter-evans/create-pull-request` 같은 서드파티 액션).

---

## Good practices observed (칭찬할 만한 점)

- 시크릿/캐시/로컬 아티팩트 git 제외: `.gitignore:3-19` (`.env`, `data/`, `holdings.yaml`, `reports/`, `web/node_modules/` 등).
- 시크릿의 YAML 저장 금지(실패-폐쇄): `sab/config.py:159-166`.
- YAML 파싱 안전 옵션 사용: `sab/config_loader.py:38-53`, `sab/holdings_loader.py:67-83`.
- 토큰/캐시 원자적 저장: `sab/utils/atomic_io.py:32-62`, `sab/data/cache.py:19-23`.
- Next.js 서버 전용 모듈 분리(`server-only`): `web/src/lib/env.server.ts:1`, `web/src/lib/supabase-admin.ts:1`, `web/src/lib/github-actions.ts:1`.
- Supabase 쪽 최소 공개:
  - holdings RLS 강제 + anon/auth revoke: `supabase/migrations/20260213095830_enable_rls_holdings.sql:1-5`
  - reports bucket 비공개 + mime allowlist: `supabase/migrations/20260213102000_create_reports_bucket.sql:1-5`

## Recommended next steps (우선순위)

1. “진짜 로컬 전용”이면: `docker-compose.yml` 포트를 loopback으로 묶고(SBP-001), `/api/run`·`/api/reports*`도 로컬 제한 적용.
2. LAN 접근이 필요하면: Host allowlist 대신 **인증 경계(공유 시크릿/Basic Auth 등)**를 추가하고, `/api/run`의 `ref`는 고정/allowlist로 제한(SBP-003).
3. 공급망 하드닝: Dockerfile pnpm 설치 방식(corepack/검증) + GitHub Actions SHA pinning(SBP-005/006).

