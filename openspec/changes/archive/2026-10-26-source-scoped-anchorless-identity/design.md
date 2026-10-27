## Context

The 40x fix (migration 0018) gave anchorless raw observations a content-addressed identity but
omitted the source from the key. Verified on the real catalog (audit copy, schema 15): 20
anchorless `candidate_lookup` observations, 5 duplicate groups — 3 same-platform retries (true
duplicates) and 2 danbooru/aibooru groups where both instances returned byte-identical bodies.
Under 0018 the second source's observation can never land; the shared row keeps the first
writer's `platform_id`/`schema_version`. Sharing across requests already exists in the data
(observation 3165 is referenced by two requests), so sharing itself is sound; only its scope is
wrong.

## Goals / Non-Goals

Goals: source-scoped anchorless identity; the sharing blessed in writing at both call sites; a
provable repair path so the real catalog migrates through 0018 → 0019; tests pinning all of it.

Non-Goals: re-anchoring the candidate-lookup/probe flows to their runs (the rejected 7o0 option);
repairing the real catalog automatically from this change (operator runs the script);
retroactively recreating the two folded cross-platform observations (their attempts live in the
request ledger; the fold is reported, not reversed).

## Decisions

### D1: platform_id joins the anchorless identity; anchorless requires a source

Both anchorless flows (`CandidateLookupService._retain_response`, `LibraryCountProbeService.probe`)
always declare a platform, so `store_raw` refuses an anchorless insert without one — identity stays
a plain column key, no `COALESCE` expression indexes. Platform-less source reports remain possible
through import-run anchoring, which has its own identity.

### D2: The repair dedups under the stricter 0018 definition, deliberately

The migration chain runs 0018 before 0019, and 0018 fails loudly on *any* 0018-duplicate — so the
repair must remove all five groups here, including the two cross-platform ones, folding them
first-writer-wins (the loser platform's attestation survives in its request/run ledger). The repair
report lists same-platform folds and cross-platform folds separately so the operator sees exactly
what historical nuance is being folded. After 0019, the cross-platform class can never recur.

### D3: Repair mechanics follow the 0018 comment's surgery, generalized

For each 0018-duplicate group: keep the earliest row; for each other member, dynamically discover
referencing rows (every table with a `raw_observation_id` column, discovered from the schema, not
hardcoded) and re-point them to the keeper — re-pointing requires temporarily dropping the
update-blocking triggers on those tables, recreated afterwards from their stored `sqlite_master`
SQL verbatim; unreferenced members are deleted (the `raw_observations` immutability triggers drop
and recreate likewise). Dry-run is the default and prints the full plan; `--apply` executes inside
one transaction and finishes with `PRAGMA foreign_key_check` and a re-scan proving zero groups
remain under both the 0018 and 0019 definitions.

### D4: Spec now names the identity rule

The 40x fix shipped without a spec statement; this change's kernel requirement covers both halves
(anchor-scoped or source-scoped content addressing) so the rule is testable from here on.

## Risks / Trade-offs

- [Trigger surgery on the real catalog] → Script is dry-run by default, proven against a copy of
  the real catalog first; triggers are recreated from stored SQL verbatim; one transaction; FK
  check before commit.
- [Re-pointed references rewrite audit rows] → Only the `raw_observation_id` pointer changes; the
  0018 comment sanctions re-pointing explicitly; the repair report records every re-point.
- [Folded cross-platform history] → Accepted and reported (D2); ledger retains both attempts; the
  new identity prevents recurrence.
- [A future anchorless flow without a platform] → Refused loudly at `store_raw`; it must anchor to
  a run or declare a source.

## Migration Plan

Migration 0019 drops 0018's two indexes and creates the platform-scoped replacements (index-only;
no table rebuild). Run order for a damaged catalog: repair script at schema ≤ 17 → migrate
(0018 passes, 0019 re-scopes). Undamaged catalogs migrate straight through.

## Open Questions

None blocking.
