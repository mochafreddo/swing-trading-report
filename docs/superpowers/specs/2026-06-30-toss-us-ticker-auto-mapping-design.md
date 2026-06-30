상태: Accepted

# Toss US Ticker Auto Mapping Design

## Goal

Toss holdings sync should stop blocking US holdings when the app already has one
trusted canonical ticker candidate for the Toss symbol. The sync must still
block ambiguous or unknown mappings so it does not write holdings under the
wrong exchange suffix.

## Policy

For US Toss items, resolve the suffix in this order:

1. Existing Supabase holdings with exactly one matching explicit suffix.
2. The app ticker directory or recent buy-derived directory with exactly one
   matching ticker whose base symbol equals the Toss symbol, only when that
   directory was built from at least one fresh source report.
3. Block with `ticker_exchange_unresolved` when there are zero or multiple
   candidates, or when the directory is stale/empty.

KR symbols keep the current direct 6-digit mapping. Unknown market/currency and
invalid decimals remain blocked.

## Data Flow

`/api/holdings/toss-sync` fetches current holdings, Toss holdings, and a
server-side ticker directory snapshot. The Toss normalizer receives the directory
candidates as an optional resolver input. It never receives browser-provided
mappings and never exposes Toss tokens or account metadata.

Dry-run and apply both recompute the same mapping and `diffHash`. Apply still
requires the reviewed hash, server-side confirmation text, and still refuses
blocked or stale diffs.

## Testing

Add unit coverage for:

- unresolved US symbols map to a directory candidate when there is exactly one
  matching suffix.
- ambiguous directory matches stay blocked.
- existing holdings mapping remains the first-choice source.
- ambiguous existing holdings stay blocked before directory fallback.
- stale directory data is not used as an automatic mapping source.
- class-share symbols such as `BRK/B` resolve to canonical `BRK.B.*` bases.

Add route coverage that proves dry-run can create a new US holding from a
directory-backed Toss symbol without writing Supabase, and that apply requires
`confirmationText: "APPLY TOSS HOLDINGS"` before writing Supabase.
