# Evidence Ledger Console Design System

상태: Accepted (V1 implementation)  
Scope: Authenticated local app-console UI for `swing-trading-report`  
Source design: local gstack artifact
`~/.gstack/projects/mochafreddo-swing-trading-report/mochafreddo-main-design-20260707-232702.md`
(provenance only; not required to consume this repo document)

## 문서 상태

### 현재 제공

- Evidence Ledger V1 app-console UI, interaction, hierarchy, state, and
  responsive rules are accepted as the current design source of truth.
- The static Reports proof documents the first implementation target before
  React/CSS changes land in `web/src/**`.

### 실험

- No separate experimental design-system tree is active.
- Future visual variants should be promoted here only after they preserve the
  Evidence Ledger task order and state contracts.

### 백로그

- App shell/token retargeting, Reports React implementation, Holdings, Metrics,
  and Run applications are tracked as phased V1 follow-up work below.

### 폐기 후보

- Dark/glass/hero-style authenticated console treatments are deprecated for V1
  app-console surfaces and should be removed as implementation phases land.

## Source Of Truth

This document owns UI, interaction, visual hierarchy, state presentation, and
responsive behavior for the local web console. It does not own trading strategy,
report schema, runtime topology, or API behavior.

| Concern | Source of truth |
| --- | --- |
| UI design, layout, component vocabulary, status presentation | `DESIGN.md` |
| Swing signal, risk, readiness, and trading-rule semantics | `docs/STRATEGY.md` |
| Component/data flow, services, storage, APIs, scheduler architecture | `docs/ARCHITECTURE.md` |
| CLI/API contracts | `docs/api.md` |
| Operations and deployment | `docs/operations.md`, `docs/deployment.md` |

First implementation PR boundary:

- In scope: this document, `docs/README.md`, and
  `docs/design/reports-evidence-ledger-proof.html`.
- Out of scope: `web/src/**`, CSS token retargeting, app shell changes, Reports
  React changes, Holdings/Metrics/Run refactors, new dependencies, and report
  schema changes.

This document intentionally excludes session coaching notes, gstack review
reports, implementation metadata, and personal observations from the source
design conversation.

## Design Thesis

> A calm evidence ledger for morning trading decisions.

The console does not make the user's trading decision. It makes each judgment
auditable: what was recommended, what rule or AI layer produced it, whether the
evidence is fresh, what source coverage is missing, what is blocked, and what the
next safe action is.

## Core Principles

1. **Evidence adjacent to judgment**: confidence, score, recommendation, and
   status labels are incomplete without nearby basis and freshness.
2. **Quiet until it matters**: normal data is neutral. `BLOCKED`, `STALE`,
   weak source coverage, manual review, destructive actions, and quality-gate
   failures get stronger treatment.
3. **Rule and AI separation**: deterministic `sab` results and AI Brief
   interpretation stay visually distinct. AI is an explanation/review layer, not
   the source of deterministic readiness.
4. **Ledger density**: prefer tables, compact rows, metadata strips,
   disclosure, and sticky structure over decorative card grids.
5. **Freshness is first-class**: report date, `generated_at`, source coverage,
   Toss sync state, and runtime marker state must not be hidden in footers.
6. **Risk controls earn friction**: destructive apply/delete, workflow runs, and
   notification sends require clear confirmation and post-action proof.
7. **Copy is operational**: text states what happened, what is blocked, what is
   missing, and what the user can do next. No marketing language inside normal
   workflows.

## Visual Direction

V1 is light-first and evidence-first. The desired feel is closer to a
Linear/Stripe-style operational console than to a neon trading dashboard.

Foundation token target for later implementation:

```text
--bg: #f7f8fb
--surface: #ffffff
--surface-subtle: #f3f5f8
--surface-raised: #ffffff
--line: #d8dee8
--line-strong: #b8c1cf
--ink: #101828
--ink-soft: #344054
--ink-muted: #667085
--accent: #2563eb
--evidence: #0f766e
--ok: #15803d
--warn: #b45309
--danger: #b42318
--blocked-bg: #fff7ed
--review-bg: #fffbeb
--success-bg: #ecfdf3
--info-bg: #eff6ff
--radius-control: 6px
--radius-panel: 8px
--shadow-panel: 0 1px 2px rgba(16, 24, 40, 0.06)
```

Hard rules:

- Use calm surface hierarchy, restrained color, crisp typography, and minimal
  chrome.
- Use cards only when the card is the interaction or a bounded repeated item.
- Prefer tables, compact rows, sticky headers, disclosure, and status columns
  over decorative dashboard widgets.
- Keep raw JSON as an audit/debug escape hatch, not the primary reading
  experience.
- Do not communicate status by color alone.
- Do not use gradient orbs, bokeh, decorative glassmorphism, large centered hero
  copy, card-inside-card layouts, or purple/blue gradients as the dominant app
  identity.

## Typography

- Keep `Inter` as the V1 console font because the existing font variable
  contract already depends on it.
- Keep `--font-display` for compatibility, but app-console surfaces should alias
  display treatment toward body typography during V1.
- Console page headings target 24-28px desktop and 20-22px mobile.
- Labels use 12-13px only for short metadata; do not use all-caps for long
  Korean text.
- Use tabular numbers for prices, counts, dates, ratios, coverage, and P/L.

## Token Alignment

| Existing vocabulary | V1 treatment | Notes |
| --- | --- | --- |
| `--space-1` through `--space-12` | Preserve | Existing spacing scale remains useful. |
| `--font-inter`, `--font-body`, `--font-mono` | Preserve | Body and monospace contracts stay stable. |
| `--font-space-grotesk`, `--font-display` | Compatibility alias | Keep variables; avoid display styling in app-console surfaces. |
| `--bg`, `--panel`, `--panel-strong` | Retarget | Move from dark/glass surfaces to light neutral background/surface tokens. |
| `--line`, `--line-strong`, `--line-focus` | Preserve and retarget | Keep names; verify focus behavior on light surfaces. |
| `--ink`, `--ink-soft`, `--ink-muted` | Preserve and retarget | Keep semantic text levels; verify contrast. |
| `--accent`, `--accent-strong`, `--accent-soft`, `--accent-bg` | Preserve with restraint | Accent is for navigation/action emphasis, not decoration. |
| `--ok`, `--warn`, `--danger` | Preserve | Use only through status semantics. |
| `--violet`, `--fuchsia`, decorative gradient tokens | Deprecate for app surfaces | Do not use as dominant identity in V1 console routes. |
| `--radius`, `--radius-sm`, `--radius-lg` | Retarget | Add semantic aliases `--radius-control` and `--radius-panel`. |
| `--shadow-lg` | Retarget or avoid | Panels should rely on border and hierarchy first. |

## Layout System

Global app shell:

- Replace hero-scale authenticated console headers with a compact shell.
- Desktop top area target: 56-64px.
- Navigation is a compact tab row or left-aligned top nav.
- Page title belongs inside the page workspace, not in a marketing-style hero.

Desktop content:

- Max content width: 1280px.
- Outer page padding: 24px desktop, 16px tablet/mobile.
- Common two-column operational layout: 300-340px task rail plus
  `minmax(0, 1fr)` main workspace with a 16-20px gap.
- Panels are for bounded tools, repeated items, and detail surfaces.

Mobile content:

- App shell/nav compacts at `680px`.
- Reports selector/detail becomes one column at `960px`.
- Holdings task rail/workspace becomes one column at `1100px`.
- Metrics groups become one column at `840px`.
- Run config/result becomes one column at `960px`.
- Preserve task order; do not merely stack desktop cards.

## Responsive and Accessibility

Responsive behavior must preserve the morning task order: orientation, trust
state, evidence, blocker, action.

| Viewport | App shell | Reports | Holdings | Metrics | Run |
| --- | --- | --- | --- | --- | --- |
| Desktop `>=1280px` | Compact top bar/nav; max 1280px | Selector/detail split | Task rail plus holdings table | Grouped health panels | Config/result split |
| Tablet `840-1279px` | Nav may wrap; labels remain visible | Split until 960px | Split until 1100px | Grouped one-column below 840px | Split until 960px |
| Mobile `390-839px` | Compact nav at 680px; no unlabeled icon-only route hiding | Status, selector/filter, summary, rows, raw JSON footer | Status summary, task panels when immediate, table/key rows | Latest/sample/source before charts | Preflight, action, result, recovery |
| Narrow `<390px` | Labels wrap; text stays readable | Stacked key/value rows | Horizontal table scroll only after summary | Hide decoration before meaning | Buttons stack with 44px targets |

Accessibility rules:

- Every interactive element is keyboard reachable in visible task order.
- Each page has one `h1`; panel headings do not skip levels.
- Focus indicators remain visible on light surfaces.
- Disclosure rows expose `aria-expanded`.
- Loading/result updates use polite live regions when content changes without
  navigation.
- Status badges include text labels in the DOM; color and icon are supporting
  signals only.
- Muted text must not carry blockers, stale states, weak sources, validation
  failures, or next actions.

## Information Architecture

V1 keeps the existing route set and changes the hierarchy from decorated
dashboard pages to a morning evidence workspace.

```text
App
├─ Login / session gate
└─ Console Shell
   ├─ Top Bar
   │  ├─ Product label: Swing Trading Report
   │  ├─ Current workspace title
   │  ├─ Freshness/session summary when available
   │  └─ Safe global actions only
   ├─ Navigation
   │  ├─ Reports
   │  ├─ Holdings
   │  ├─ Metrics
   │  └─ Run
   └─ Workspace
      ├─ Page header: task-specific title, status, compact actions
      ├─ Primary evidence/action surface
      ├─ Secondary context or task rail
      └─ State footer: source, generated_at, blockers, recovery
```

| Route | Primary job | First | Second | Third |
| --- | --- | --- | --- | --- |
| Reports | Verify a generated trading judgment | Selected report trust state | Candidate evidence rows | Raw JSON / secondary metadata |
| Holdings | Safely mutate current holdings | Active holdings / sync state | Bulk mutation task rail | Destructive or inactive states |
| Metrics | Check generation and delivery health | Run health summary | Evidence completeness trends | Detailed samples / history |
| Run | Trigger a controlled workflow | Preflight readiness | Workflow action | Result and recovery |

## Reports Proof Contract

Reports is the first Evidence Ledger proof screen.

```text
Reports Workspace
├─ Page Header
│  ├─ Title: Reports
│  ├─ Selected report: type, session date, generated_at
│  ├─ Canonical status: READY / REVIEW / STALE / WEAK_SOURCE / BLOCKED
│  └─ Actions: refresh/list controls
├─ Report Selector
│  ├─ Search / filter by type and date
│  ├─ Report rows
│  │  ├─ report type + session date
│  │  ├─ candidate count
│  │  ├─ source/freshness badge
│  │  └─ notification/runtime badge
│  └─ Empty/error state with one next action
├─ Detail Evidence Ledger
│  ├─ Evidence summary strip
│  │  ├─ source coverage
│  │  ├─ rule-vs-AI boundary
│  │  ├─ freshness
│  │  └─ blocker count
│  ├─ Candidate evidence rows
│  │  ├─ ticker/entity
│  │  ├─ judgment
│  │  ├─ deterministic rule basis
│  │  ├─ AI interpretation when present
│  │  ├─ freshness/source state
│  │  ├─ risk/blocker
│  │  └─ next action
│  └─ Row disclosure for secondary evidence
└─ Utility Footer
   ├─ source file / report key
   ├─ generated_at / stale rule
   ├─ preserved raw JSON access as an audit/debug escape hatch
   └─ recovery note for partial or failed data
```

Static proof artifact:

- Canonical file: `docs/design/reports-evidence-ledger-proof.html`.
- `/private/tmp/reports-evidence-ledger-proof.html` may be used only as a local
  preview copy.
- Use synthetic or redacted data only.
- Do not depend on external fonts, CDNs, scripts, images, or network resources.
- Include `READY`, `REVIEW`, `STALE`, `WEAK_SOURCE`, and `BLOCKED`.
- Include field-specific fallback copy for missing rule basis, AI evidence,
  freshness, and source coverage.
- Review around 1280px desktop and 390px mobile before Reports CSS refactor.

## Component Anatomy

### Panel

Use panels for bounded tools and evidence groups.

- Radius: 8px.
- Border: visible 1px neutral line.
- Shadow: subtle or none.
- No nested panels; use section dividers inside a panel.
- Header metadata must be scannable before body details.

### Evidence Row

Evidence row order:

```text
Ticker / Entity
Judgment + primary rule basis
AI interpretation
Freshness / source coverage
Risk / blocker
Next action
```

Rules:

- A row without basis or freshness is incomplete.
- AI interpretation never overwrites rule basis.
- Missing source coverage renders as `Weak sources`, `Stale`, or `Unavailable`,
  not as blank muted text.
- Manual review rows show why review is required before any action.

Display contract by report type:

| Report type | Judgment source | Primary evidence fields | Freshness/source fields | Missing-data fallback |
| --- | --- | --- | --- | --- |
| `buy` / `scan` | deterministic scan row | `ticker`, `action`, `pattern`, `quality_state`, score, risk alignment, reasons/issues | `date`, `generated_at`, provider/source fields | `Evidence unavailable` for the missing field |
| `sell` | deterministic sell row | `ticker`, `action`, `reasons`, `pnl_pct`, stop/target guide, `entry_pattern` | report `date`, `generated_at`, holdings marker | `Rule reason missing` |
| `entry` | deterministic entry policy | `entry_action`, `candidate_role`, readiness, liquidity, downside risk, exposure buckets | source report/date, `generated_at` | `Context required` |
| `ai-brief` | AI interpretation of deterministic candidates | recommendation, candidate role, rationale, veto/review fields | source coverage counts and provider statuses | `AI evidence incomplete` |
| `sell-ai-brief` | AI interpretation of sell candidates | sell action, AI judgment/rationale, source-backed reasons, review flags | sell coverage/provider status, `generated_at` | `Sell AI evidence incomplete` |
| `ai-brief-skip` | scheduler/runtime status | `skip_state`, `skip_reason`, expected/session state | session date, `generated_at`, runtime marker | `Skipped` with explicit reason |
| `backtest` | historical replay result | trades, win rate, return, drawdown, assumptions | data file/date range, config snapshot | `Backtest evidence incomplete` |

This matrix is a display contract, not a new report schema.

### Status Badge

Badges combine semantic label, tone, shape/border, and optional short reason.
They never rely on color alone.

| Status | Tone | Meaning |
| --- | --- | --- |
| `READY` | success | deterministic checks passed and evidence is fresh enough |
| `REVIEW` | warning | valid candidate, but human review required |
| `BLOCKED` | danger | action/report cannot proceed |
| `STALE` | warning | data exists but is too old for normal trust |
| `WEAK_SOURCE` | warning | source coverage is below confidence threshold |
| `SENT` | success | notification/delivery completed |
| `FAILED` | danger | operation failed and needs attention |
| `SKIPPED` | neutral | intentionally not run or no-op |

Status derivation rules:

- Prefer backend/report-provided statuses over frontend inference.
- `STALE` uses explicit artifact freshness when present; otherwise show
  freshness unknown/stale instead of assuming normal freshness.
- `WEAK_SOURCE` uses source/eval status when present. If only coverage counts
  are available, show weak source when covered count is below total count.
- `BLOCKED` covers validation failure, missing/stale Toss freshness,
  quality-gate failure, or impossible apply state.
- `READY` is only shown when the artifact or view model indicates readiness.
  Do not infer readiness from absence of errors.

### Buttons, Forms, Tables

- Primary button: one safe main action per panel.
- Secondary button: non-destructive support.
- Destructive button: red tone plus exact confirmation for broad mutation.
- Ghost button: row action or low-emphasis navigation.
- Buttons keep width stable during loading and explain disabled state when the
  reason is not obvious.
- Forms use labels above controls, helper text near the field, field-level error
  copy, and panel-level error summaries for submit failures.
- Tables are first-class. Use compact headers, tabular right-aligned numeric
  columns, status/source columns, controlled wrapping, and disclosure for
  secondary evidence.

## Interaction State Coverage

State UI describes what the user sees, not only what the backend is doing.
Preserve trustworthy prior data, label freshness, and make the next safe action
obvious.

| Feature | Loading | Empty | Error | Success | Partial |
| --- | --- | --- | --- | --- | --- |
| App shell / session | Compact skeleton after session check starts | Login/session gate | Session failure plus retry/sign-out | Compact nav and route | Shell remains, auth-dependent content disabled |
| Reports selector | Keep prior list with `Refreshing` meta | `No reports yet` plus one action | Preserve last safe list and show retry | Rows show type/date/count/freshness | Rows with missing metadata show `Evidence incomplete` |
| Reports detail | Keep selected detail with stale marker | `Select a report` or no-candidates copy | Keep report key visible and offer retry/raw debug | Header, summary, evidence rows, raw JSON toggle | Field fallback labels such as `Rule reason missing`, `AI evidence incomplete`, `Source coverage unavailable` |
| Evidence row | Preserve ticker/entity and prior status | Parent owns empty state | Mark exact missing proof as `BLOCKED` or `FAILED` | Judgment, rule, AI, freshness, risk, action visible | Missing evidence keeps row visible with fallback status |
| Holdings | Current holdings remain visible while sync/apply runs | Flat portfolio or setup state | Failed load/apply plus preserved state | Active holdings with sync evidence | Incomplete sync badge; destructive actions guarded |
| Metrics | Last metrics visible with freshness marker | No metrics yet plus workflow hint | Failed load plus preserved sample | Health groups answer named questions | Missing samples show denominator/fallback |
| Run | Preflight rows resolve independently | Missing env/config checklist | Failed preflight/trigger with recovery | What will run and result proof | Mixed pass/block keeps action disabled with blockers |
| Shared table | Stable dimensions | Empty body with one action | Error row or panel state | Header, sort, badges, disclosures usable | Missing cells show explicit fallback copy |

Rules:

- Loading must not erase trustworthy prior evidence unless it could mislead.
- Empty states say whether absence is normal, expected, or setup-related.
- Error states separate nothing-loaded from some-evidence-missing.
- Success states stay quiet.
- Partial states use warning/neutral badges and field-specific fallback copy.
- Every state needs keyboard-visible focus behavior for available actions.

## Screen Applications

### Reports

- List items show report type, session date, `generated_at`, candidate counts,
  weak source/stale markers, and notification/runtime state.
- Detail header shows report identity, source coverage, and rule/AI boundary.
- Candidate rows show ticker, judgment, rule basis, AI interpretation,
  freshness, source coverage, risk caveat, and next action.
- Raw JSON remains available from the utility footer, not as a primary action.
- Before visual refactor, define report view-model helpers that expose
  `judgment`, `ruleBasis`, `aiInterpretation`, `freshness`, `sourceCoverage`,
  `riskBlocker`, and `nextAction` with fallback copy.

### Holdings

- Holdings is the guarded state mutation workspace.
- Toss Sync and YAML import share dry-run, diff, confirm, apply, verify visual
  states where behavior exists.
- Delete/inactive states use destructive/status vocabulary consistently.
- The table prioritizes active holdings, entry pattern, risk override, latest
  update, and broker sync evidence.

### Metrics

- Metrics are health evidence, not decorative chart cards.
- Group by named health questions: generation, evidence completeness, delivery,
  blockers.
- Each metric needs latest value, average/trend where relevant, sample size, and
  generated/source note.

### Run

- Before running, show workflow, branch/source, required env/config, and blockers.
- During run, show durable status and links.
- After run, show result, artifact/report link, notification state, and recovery.

## Migration Plan

| Phase | Scope | Acceptance |
| --- | --- | --- |
| V1.0 `DESIGN.md` | Repo-root design rules and Reports proof mock | `DESIGN.md`, `docs/README.md`, and tracked mock exist; no `web/src/**` changes |
| V1.1 App shell/tokens | Global CSS tokens, compact shell, top nav | `/login` and console routes no longer depend on hero-scale dark/glass identity; tests pass |
| V1.2 Reports proof | Report list/detail evidence rows and badges | Committed proof mock approved first; rows show judgment, basis, freshness/source state, fallback copy |
| V1.3 Holdings | Bulk mutation panels and table visual vocabulary | Toss/YAML panels share visual states; destructive actions remain guarded |
| V1.4 Metrics/Run | Health evidence groups and controlled action states | Mobile metrics grouped; Run shows preflight/result/failure recovery |

V1.2 may require report view-model normalization. Treat that as an
implementation prerequisite, not a CSS task.

## Not In Scope

| Deferred item | Rationale |
| --- | --- |
| Dark mode | V1 is light-first to improve trust, scan speed, and implementation focus. |
| Left rail navigation | Current route count fits compact top navigation. |
| New UI framework/component library | Existing Next.js/CSS module structure is enough for V1. |
| New icon dependency | Badges and controls must work with text, tone, border/fill, and shape first. |
| Marketing/landing redesign | The product surface is a local authenticated operations console. |
| Route restructuring | V1 preserves route structure and proves vocabulary first. |
| Trading logic/report schema redesign | The UI displays existing data and fallback copy. |
| Automated broker execution | The UI supports evidence and guarded state mutation, not execution pressure. |
| Decorative visual identity exploration | No gradient orbs, glassmorphism, bokeh, hero treatment, or generic SaaS decorative system in V1. |

## Verification

First documentation/proof PR:

```bash
rg -n "Evidence Ledger|Information Architecture|Interaction State Coverage|Responsive and Accessibility" DESIGN.md
rg -n "READY|REVIEW|STALE|WEAK_SOURCE|BLOCKED|Rule reason missing|AI evidence incomplete|freshness|source coverage" docs/design/reports-evidence-ledger-proof.html
```

Also review `docs/design/reports-evidence-ledger-proof.html` around 1280px
desktop and 390px mobile before V1.2 CSS implementation starts.

Future web implementation PRs use `just ci-web`, component tests for changed
behavior/state rendering, visual smoke on affected routes, keyboard/focus checks,
and mobile/desktop layout checks.
