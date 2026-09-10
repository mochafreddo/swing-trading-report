# Issue tracker: GitHub

작업 이슈는 `mochafreddo/swing-trading-report`의 GitHub Issues에서 관리한다. 저장소 안에서 `gh` CLI를 사용한다.

## 작업 규칙

- 이슈 목록: `gh issue list --state open --json number,title,body,labels`
- 이슈와 댓글 조회: `gh issue view <number> --comments`
- 이슈 생성: `gh issue create --title "<title>" --body-file <file>`
- 댓글 작성: `gh issue comment <number> --body-file <file>`
- 라벨 추가·제거: `gh issue edit <number> --add-label "<label>"` 또는 `--remove-label "<label>"`
- 이슈 종료: `gh issue close <number>`

여러 줄 본문은 임시 파일에 작성하고 `--body-file`로 전달한다. 변경은 해당 사용자 요청에서 승인된 범위로 수행한다.

스킬이 “이슈 트래커에 발행”을 지시하면 GitHub 이슈를 생성한다. “관련 티켓 조회”를 지시하면 이슈 본문과 댓글을 읽는다.

## Pull requests as a triage surface

**PRs as a request surface: no.**
