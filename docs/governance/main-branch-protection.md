# main 브랜치 보호 운영 가이드

- 상태: Accepted
- 최종 갱신: 2026-02-21
- 범위: `mochafreddo/swing-trading-report` 저장소의 `main` 브랜치

## 1) 현재 적용 정책(1단계)

`main`은 classic branch protection으로 관리합니다.

- `required_status_checks.strict=true`
- Required status checks:
  - `Ruff + Mypy + Pytest (Python 3.13)`
  - `Next.js Web (Lint + Typecheck + Test + Build)`
  - `workflow_audit`
  - `security_audit`
- `enforce_admins=true`
- `required_pull_request_reviews.required_approving_review_count=0`
- `required_pull_request_reviews.require_code_owner_reviews=false`
- `required_pull_request_reviews.dismiss_stale_reviews=false`
- `required_conversation_resolution=true`
- `allow_force_pushes=false`
- `allow_deletions=false`
- `required_linear_history=false`
- `required_signatures=false` (2단계에서 적용 예정)

참고 파일:

- 기준 payload: `docs/governance/main-branch-protection.stage1.payload.json`
- 적용 직후 응답: `docs/governance/main-branch-protection.applied.json`
- 현재값 재조회: `docs/governance/main-branch-protection.current.json`
- 기준선 스냅샷: `docs/governance/main-branch-protection.snapshot.json`
- payload는 GitHub Actions `app_id`를 고정하지 않고 `contexts`만 선언해 환경 이관 시 재적용 실패를 줄입니다.

## 2) Required check 이름 동기화 절차

워크플로 `job.name`이 변경되면 브랜치 보호의 required check 컨텍스트도 함께 변경해야 합니다.

1. 워크플로 job 이름 변경 (`.github/workflows/*.yml`)
2. `docs/governance/main-branch-protection.stage1.payload.json`의 check context 이름 동기화
3. 보호 설정 재적용:

```bash
gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  repos/mochafreddo/swing-trading-report/branches/main/protection \
  --input docs/governance/main-branch-protection.stage1.payload.json
```

4. drift 확인:

```bash
gh api repos/mochafreddo/swing-trading-report/branches/main/protection \
  > docs/governance/main-branch-protection.current.json

jq '{
  required_status_checks: {
    strict: .required_status_checks.strict,
    contexts: .required_status_checks.contexts
  },
  enforce_admins,
  required_pull_request_reviews,
  required_linear_history,
  allow_force_pushes,
  allow_deletions,
  block_creations,
  required_conversation_resolution,
  lock_branch,
  allow_fork_syncing
}' docs/governance/main-branch-protection.stage1.payload.json \
  > docs/governance/main-branch-protection.payload.normalized.json

jq '{
  required_status_checks: {
    strict: .required_status_checks.strict,
    contexts: .required_status_checks.contexts
  },
  enforce_admins: .enforce_admins.enabled,
  required_pull_request_reviews: {
    dismiss_stale_reviews: .required_pull_request_reviews.dismiss_stale_reviews,
    require_code_owner_reviews: .required_pull_request_reviews.require_code_owner_reviews,
    require_last_push_approval: .required_pull_request_reviews.require_last_push_approval,
    required_approving_review_count: .required_pull_request_reviews.required_approving_review_count
  },
  required_linear_history: .required_linear_history.enabled,
  allow_force_pushes: .allow_force_pushes.enabled,
  allow_deletions: .allow_deletions.enabled,
  block_creations: .block_creations.enabled,
  required_conversation_resolution: .required_conversation_resolution.enabled,
  lock_branch: .lock_branch.enabled,
  allow_fork_syncing: .allow_fork_syncing.enabled
}' docs/governance/main-branch-protection.current.json \
  > docs/governance/main-branch-protection.current.normalized.json

diff -u \
  docs/governance/main-branch-protection.payload.normalized.json \
  docs/governance/main-branch-protection.current.normalized.json
```

`main-branch-protection.payload.normalized.json`과
`main-branch-protection.current.normalized.json` diff가 비어 있어야 합니다.

## 3) 단독 운영 예외와 상향 트리거

현재는 직접 협업자가 1명이라 머지 병목 방지를 위해 승인 수 0 정책을 유지합니다.

- 유지 정책:
  - `required_approving_review_count=0`
  - `require_code_owner_reviews=false`
- 상향 트리거(협업자 2인 이상 또는 외부 기여 정례화):
  - `required_approving_review_count=1`
  - `require_code_owner_reviews=true`
  - `dismiss_stale_reviews=true`

## 4) 2단계(서명 커밋) 전환 체크리스트

아래 조건을 만족하면 `required_signatures=true`를 적용합니다.

1. 개발자 로컬 커밋 서명(gpg/ssh) 기본 설정 완료
2. 최근 `main` 커밋의 서명 검증 상태 점검:

```bash
gh api 'repos/mochafreddo/swing-trading-report/commits?sha=main&per_page=20' \
  --jq '.[] | [.sha[0:7], (.commit.verification.verified|tostring), .commit.verification.reason] | @tsv'
```

3. 자동화/봇 경로가 서명 정책과 충돌하지 않는지 확인
4. 적용:

```bash
gh api --method POST \
  -H "Accept: application/vnd.github+json" \
  repos/mochafreddo/swing-trading-report/branches/main/protection/required_signatures
```

## 5) 운영 검증 시나리오

1. 관리자 계정으로 `main` 직접 push 차단 확인 (`enforce_admins`)
2. 필수 체크 4개 중 1개 실패 PR 머지 차단 확인
3. 필수 체크 4개 성공 + 대화 해결 완료 PR 머지 가능 확인
4. 워크플로 job 이름 변경 후 required check 미동기화 시 머지 차단 확인
5. (2단계 적용 후) unsigned 커밋 머지/직접 반영 차단 확인

## 6) 기준 문서

- <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches>
- <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets>
- <https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories/about-status-checks>
- <https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners>
