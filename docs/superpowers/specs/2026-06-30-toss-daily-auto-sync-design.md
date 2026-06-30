상태: Draft for Review

# Toss Daily Auto Sync Design

## Goal

Holdings should automatically match the Toss Securities account once per day,
without manual `APPLY TOSS HOLDINGS` typing or button clicks. The operator chose
Toss as the source of truth for automatic `create`, `update`, and `delete`
changes.

The first implementation should keep the existing manual Toss Sync panel, but
add a trusted local scheduled path that runs the same reconciliation and apply
logic at an appropriate daily time.

## Non-Goals

- Do not port the Toss sync implementation to Python in the first release.
- Do not make GitHub-hosted scheduled workflows the primary path in the first
  release; that would require copying Toss account credentials to GitHub
  Secrets.
- Do not apply a partial diff when normalization has blocked rows.
- Do not bypass the existing local-only boundary for holdings mutation routes.

## Recommended Approach

Use a local scheduled job that calls a new trusted web endpoint backed by a
shared Toss holdings sync service.

The web app already owns the Toss client, Supabase holdings adapter, ticker
directory lookup, reconciliation, diff hashing, blocked-row policy, and
replace-all RPC call. Reusing that logic avoids a Python port and prevents route
and scheduler behavior from drifting.

The existing browser route stays admin-session protected. The new scheduled
route is separate and accepts only local requests with a dedicated job token.
This keeps browser CSRF/session rules intact while allowing non-interactive
launchd or cron execution.

## Approach Comparison

### A. Local Scheduled Web Job

This is the recommended first release.

Pros:

- Reuses the existing TypeScript Toss sync implementation.
- Keeps Toss account credentials on the local machine.
- Can run before KR market hours and before daily trading workflows.
- Minimal change to the data model.

Cons:

- Requires the local web service to be running.
- Needs one local scheduling wrapper and one job-token secret.

### B. GitHub Actions Scheduled Workflow

Pros:

- Runs even when the local web service is down.
- Uses familiar workflow observability and notifications.

Cons:

- Requires storing Toss account credentials in GitHub Secrets.
- Must either call a local-only web route, which is unsuitable from GitHub, or
  duplicate/import the web sync logic into a workflow runner.
- More sensitive operational boundary for a broker-backed mutation.

### C. Python `sab toss-sync` CLI

Pros:

- Integrates naturally with the existing Python scheduler and Docker scheduler
  service.
- Can run without the Next.js server.

Cons:

- Requires porting the Toss client and reconciliation behavior from TypeScript
  or creating a cross-runtime contract.
- Higher risk of diverging behavior between manual UI sync and scheduled sync.

## Schedule Policy

Run once per day at `08:05 Asia/Seoul`.

Reasons:

- It is after the US regular session close and typical post-market settlement
  visibility for the next Korean morning workflow.
- It is before the Korean market opens.
- It gives a small buffer before operator review or morning sell/entry checks.

The first release can run every calendar day because the job is idempotent when
there is no diff. A later refinement may restrict to weekdays or exchange
business days if Toss API limits or logs become noisy.

## Data Flow

1. A local scheduler invokes the auto-sync runner.
2. The runner sends a local POST request to the scheduled Toss sync endpoint
   with a dedicated bearer token.
3. The endpoint verifies:
   - request host/origin is local,
   - `TOSS_SYNC_JOB_TOKEN` is configured,
   - the supplied job token matches in constant time.
4. The endpoint calls a shared service that:
   - fetches current Supabase holdings,
   - fetches Toss holdings,
   - fetches ticker directory candidates for US symbols,
   - builds the Toss dry-run,
   - computes the `diffHash`.
5. If the dry-run is blocked, the service returns a skipped result and does not
   call `replace_holdings_v1`.
6. If there are no changes, the service returns a no-op result.
7. If there are changes and the safety guards pass, the service calls
   `replaceAllHoldings(targetRows)` and returns the apply result.

The existing manual route should also call the same shared service for dry-run
and apply so manual and scheduled behavior stay identical.

## Safety Policy

Automatic apply may create, update, and delete holdings. The scheduled path must
still fail closed under these conditions:

- `applyBlocked=true` because at least one Toss row cannot be normalized safely.
- The Toss snapshot has zero incoming rows while Supabase currently has one or
  more active holdings. This prevents an API shape change or temporary upstream
  empty response from wiping the holdings table.
- The Toss API, Supabase API, ticker directory lookup, or JSON parsing fails.
- The replace-all RPC response is malformed.
- The job token is missing, invalid, or supplied from a non-local request.

Manual UI sync may continue to show and apply a zero-row diff after review if
that becomes necessary, but the scheduled path must not automatically wipe all
holdings.

The scheduled result should include a machine-readable status:

- `applied`
- `unchanged`
- `disabled`
- `blocked`
- `wipe_guard_blocked`
- `error`

## API and Service Shape

Introduce a service module under `web/src/lib/toss/` that exposes two
operations:

- `buildTossHoldingsSyncPreview()`
- `applyTossHoldingsSyncFromPreview(preview, options)`

The existing route can keep its public response shape. Internally it should use
the service rather than owning the full orchestration.

Add a scheduled-only route such as:

`POST /api/holdings/toss-sync/scheduled`

Request:

```json
{ "mode": "auto-apply" }
```

Headers:

- `Authorization: Bearer <TOSS_SYNC_JOB_TOKEN>`
- normal local request headers from the wrapper, including a local `Origin`

Response:

```json
{
  "mode": "auto-apply",
  "status": "applied",
  "diffHash": "sha256:...",
  "summary": {
    "incomingCount": 3,
    "createCount": 0,
    "updateCount": 1,
    "deleteCount": 1,
    "unchangedCount": 1
  },
  "blockedRows": []
}
```

Do not return Toss tokens, Toss account identifiers, or raw upstream payloads.

## Local Runner

Add a small non-interactive script, for example:

`scripts/toss_daily_auto_sync.sh`

Responsibilities:

- resolve `WEB_HOST_PORT`, defaulting to `55300`,
- require `TOSS_SYNC_JOB_TOKEN`,
- call the scheduled endpoint,
- exit non-zero for `disabled`, `blocked`, `wipe_guard_blocked`, and `error`,
- print only bounded summaries without secrets or raw Toss payloads.

The script can be run by launchd on macOS. A later release can add a Docker
scheduler entry if desired, but launchd is enough for the first local daily job.

## Notifications

First release notification can be log-only if no webhook secrets are configured.

If `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` or `SLACK_WEBHOOK_URL` are already
available in the local scheduler environment, the runner may send a short
summary:

- applied: `create/update/delete/unchanged` counts,
- unchanged: no changes,
- disabled: explicit note that no write occurred because auto apply is off,
- blocked: blocked count and reasons,
- wipe guard: explicit warning that no write occurred,
- error: failure category only.

No notification should include raw account identifiers, access tokens, or
unredacted Toss responses.

## Configuration

Add documented environment variables:

- `TOSS_SYNC_JOB_TOKEN`: local scheduled job bearer token.
- `TOSS_SYNC_AUTO_APPLY_ENABLED`: defaults to disabled unless set to `1`.

Existing Toss and Supabase variables remain required:

- `TOSS_INVEST_CLIENT_ID`
- `TOSS_INVEST_CLIENT_SECRET`
- `TOSS_INVEST_ACCOUNT`
- `TOSS_INVEST_BASE_URL` optional
- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY`

The token must be stored only in `.envrc.local`, `.env.scheduler.local`, a
launchd-private environment, or another ignored local secret store.

## Documentation Updates

The implementation must update:

- `docs/api.md`: apply no longer requires `confirmationText`, and the scheduled
  route contract must be documented.
- `docs/configuration.md` and `docs/config-reference.md`: add scheduled Toss
  sync variables.
- `docs/deployment.md` or local scheduler docs: describe the launchd time,
  manual smoke command, and failure behavior.
- `docs/superpowers/specs/2026-06-30-toss-us-ticker-auto-mapping-design.md`:
  replace the stale statement that apply requires confirmation text.

## Testing

Add tests before implementation code.

Unit/service coverage:

- auto apply writes `create/update/delete` when preview has changes and no
  blocked rows.
- blocked rows skip `replaceAllHoldings`.
- empty Toss snapshot plus existing active Supabase holdings triggers
  `wipe_guard_blocked`.
- empty Toss snapshot plus no active Supabase holdings returns unchanged or
  applies no write.
- `replaceAllHoldings` result counts are propagated.

Route coverage:

- scheduled route rejects missing token.
- scheduled route rejects invalid token.
- scheduled route requires local request semantics.
- scheduled route returns `disabled` and performs no write unless
  `TOSS_SYNC_AUTO_APPLY_ENABLED=1`.
- scheduled route returns bounded result without raw Toss payloads.
- manual route still supports dry-run and reviewed apply through the shared
  service.

Runner coverage:

- missing `TOSS_SYNC_JOB_TOKEN` exits non-zero without making a request.
- applied/unchanged results exit zero.
- disabled/blocked/wipe guard/error results exit non-zero.
- output redacts secrets.

Regression checks:

- search for stale `APPLY TOSS HOLDINGS` and `confirmationText` documentation
  after the implementation.
- run web lint, typecheck, format check, and focused route/service tests.

## Rollout

1. Land the shared service, scheduled endpoint, script, and docs with
   `TOSS_SYNC_AUTO_APPLY_ENABLED` defaulting off.
2. Run a manual scheduled-endpoint smoke locally and confirm it returns
   `disabled` without writing.
3. Enable `TOSS_SYNC_AUTO_APPLY_ENABLED=1` locally.
4. Run the script manually once and confirm either `applied` or `unchanged`.
5. Install the launchd schedule for `08:05 Asia/Seoul`.
6. Watch the first scheduled run logs before relying on it operationally.

## Acceptance Criteria

- Manual Toss Sync still works from the holdings UI.
- Scheduled auto sync can run without a browser session.
- Scheduled auto sync applies `create/update/delete` when safe.
- Scheduled auto sync never writes when normalization is blocked.
- Scheduled auto sync never wipes non-empty Supabase holdings from an empty Toss
  snapshot.
- Logs and notifications contain summaries only, not secrets or raw account
  payloads.
- Documentation no longer says Toss apply requires `APPLY TOSS HOLDINGS`.
