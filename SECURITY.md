# Security Policy

이 문서는 `swing-trading-report` 저장소의 보안 취약점 신고 및 대응 정책을 정의합니다.

## 지원 범위 (Supported Versions)

현재 저장소는 릴리스 브랜치/패치 브랜치를 별도로 운영하지 않습니다.

| 버전/브랜치 | 지원 여부 | 비고 |
| --- | --- | --- |
| `main` 최신 커밋 | ✅ | 보안 수정 제공 대상 |
| 과거 커밋/포크/개별 실험 브랜치 | ❌ | 보안 패치/백포트 미지원 |

## 취약점 신고 방법 (How to Report)

취약점 신고는 **GitHub Private Vulnerability Reporting**으로만 접수합니다.

신고 채널:

1. GitHub `Security` 탭의 `Report a vulnerability` 사용

접근 불가 시:

- 공개 이슈에는 기술 세부사항/PoC/로그를 절대 올리지 말고,  
  “Private Vulnerability Reporting 접근 불가” 안내만 남겨 주세요.

포함 권장 정보:

1. 영향 범위(어떤 자산/기능이 위험한지)
2. 재현 절차(가능하면 최소 단계)
3. PoC 또는 로그(민감정보는 마스킹)
4. 예상 심각도(Critical/High/Medium/Low) 및 근거
5. 사용한 커밋 SHA/브랜치/실행 환경

## 응답 기준 (Response SLA)

- 접수 확인: 영업일 기준 72시간 이내
- 1차 분류/재현 시도: 7일 이내
- 수정 계획 공유: 14일 이내
- High/Critical 이슈 우선 처리: 가능한 가장 빠른 핫픽스 우선 적용

복잡도, 외부 의존성(KIS/Supabase/GitHub API) 영향에 따라 일정은 조정될 수 있습니다.

## 공개 정책 (Disclosure)

- 원칙: **Coordinated Disclosure**
- 패치(또는 완화책) 준비 전에는 상세 내용을 공개하지 않습니다.
- 수정 배포 후, 필요 시 영향 범위와 대응 방법을 릴리스 노트/커밋 메시지/문서로 안내합니다.

## 시크릿 유출 사고 대응

다음 값이 노출되었거나 노출이 의심되면 즉시 폐기/교체하세요.

- `KIS_APP_KEY`, `KIS_APP_SECRET`
- `SUPABASE_SECRET_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- `GITHUB_PAT`
- `SAB_SESSION_SECRET`
- `OPENAI_API_KEY`
- `AI_BRIEF_SOURCE_API_TOKEN`
- `FINNHUB_API_KEY`
- `POLYGON_API_KEY`
- `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`
- `TELEGRAM_BOT_TOKEN`, `SLACK_WEBHOOK_URL`(사용 시)

권장 순서:

1. 해당 키 즉시 폐기(revoke) 및 재발급
2. 런타임/워크플로우 시크릿 교체
3. 관련 로그/아티팩트/PR 코멘트에서 민감정보 제거
4. 영향 범위 분석 후 필요 시 사용자 공지

## 운영 보안 기본값 (Project Security Baseline)

- 시크릿은 `.env`에서만 관리하고 커밋하지 않습니다.
- `config.yaml`과 `.env`에 동일 키를 중복 정의하지 않습니다(충돌 시 실패).
- 서버 전용 키(`SUPABASE_SECRET_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `GITHUB_PAT`)를 브라우저 코드로 노출하지 않습니다.
- 웹 API는 관리자 세션 인증 + same-origin 검증을 기본 보호 경계로 사용합니다.
- CI에서 `security_audit`(Trivy: `vuln,secret`, `HIGH/CRITICAL`)를 실행합니다.

## 보상 정책 (Bug Bounty)

현재 금전적 버그바운티 프로그램은 운영하지 않습니다.
