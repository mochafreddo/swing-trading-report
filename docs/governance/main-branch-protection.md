# main 브랜치 보호 운영 가이드

상태: Accepted
최종 갱신: 2026-03-28
범위: `mochafreddo/swing-trading-report` 저장소의 `main` 브랜치

## 문서 상태

### 현재 제공

- 현재 활성 정책은 `solo-dev` classic branch protection이며, 직접 push 허용과 force-push 금지 조합을 사용합니다.
- `stage1` 복귀 payload와 drift 확인 절차는 이미 문서화되어 있고 관련 JSON artifact가 저장소에 있습니다.

### 실험

- 별도 실험 정책은 운영하지 않습니다. 브랜치 보호 변경은 `solo-dev` 또는 `stage1` 기준으로만 관리합니다.

### 백로그

- PR 기반 `stage1` 복귀와 `required_signatures=true` 2단계 적용은 backlog 운영 절차입니다.

### 폐기 후보

- 예전 정책값을 수동으로 기억해 적용하는 방식은 유지하지 않고, 저장소의 payload/current artifact를 기준으로만 관리합니다.

## 1) 현재 활성 정책(임시 solo-dev)

`main`은 classic branch protection으로 관리합니다.

- `required_status_checks=null` (required check 미사용)
- `required_pull_request_reviews=null` (PR 필수 아님)
- `enforce_admins=true`
- `required_conversation_resolution=false`
- `allow_force_pushes=false`
- `allow_deletions=false`
- `required_linear_history=false`
- `required_signatures=false` (2단계에서 적용 예정)

참고 파일:

- solo-dev payload: `docs/governance/main-branch-protection.solo-dev.payload.json`
- 현재값 재조회: `docs/governance/main-branch-protection.current.json`

## 2) 강화 기준 정책(stage1, 복귀용)

PR 기반 운영으로 복귀할 때는 아래 stage1 정책을 적용합니다.

- `required_status_checks.strict=true`
- Required status checks:
  - `Ruff + Mypy + Pytest`
  - `Next.js Web (Lint + Typecheck + Test + Build)`
  - `workflow_audit`
  - `security_audit`
- `required_pull_request_reviews.required_approving_review_count=0`
- `required_pull_request_reviews.require_code_owner_reviews=false`
- `required_pull_request_reviews.dismiss_stale_reviews=false`
- `required_conversation_resolution=true`

참고 파일:

- stage1 payload: `docs/governance/main-branch-protection.stage1.payload.json`
- 적용 직후 응답: `docs/governance/main-branch-protection.applied.json`
- 기준선 스냅샷: `docs/governance/main-branch-protection.snapshot.json`
- payload는 GitHub Actions `app_id`를 고정하지 않고 `contexts`만 선언해 환경 이관 시 재적용 실패를 줄입니다.

## 3) 모드 전환 절차

### 3-1) solo-dev 적용(직접 push 허용)

```bash
gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  repos/mochafreddo/swing-trading-report/branches/main/protection \
  --input docs/governance/main-branch-protection.solo-dev.payload.json
```

### 3-2) stage1 적용(PR 기반 운영)

```bash
gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  repos/mochafreddo/swing-trading-report/branches/main/protection \
  --input docs/governance/main-branch-protection.stage1.payload.json
```

## 4) Required check 이름 동기화 절차

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

## 5) 단독 운영 예외와 상향 트리거

현재는 직접 협업자가 1명이라 머지 병목 방지를 위해 승인 수 0 정책을 유지합니다.

- 유지 정책:
  - `required_approving_review_count=0`
  - `require_code_owner_reviews=false`
- 상향 트리거(협업자 2인 이상 또는 외부 기여 정례화):
  - `required_approving_review_count=1`
  - `require_code_owner_reviews=true`
  - `dismiss_stale_reviews=true`

## 6) 2단계(서명 커밋) 전환 체크리스트

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

## 7) 운영 검증 시나리오

1. solo-dev에서 관리자 계정으로 `main` 직접 push 허용 확인
2. solo-dev에서 force push 및 브랜치 삭제 차단 확인
3. stage1 적용 후 필수 체크 4개 중 1개 실패 PR 머지 차단 확인
4. stage1 적용 후 필수 체크 4개 성공 + 대화 해결 완료 PR 머지 가능 확인
5. (2단계 적용 후) unsigned 커밋 머지/직접 반영 차단 확인

## 8) 기준 문서

- <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches>
- <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets>
- <https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories/about-status-checks>
- <https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners>
