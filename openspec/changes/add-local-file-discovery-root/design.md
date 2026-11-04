# Design

## Context

- `DiscoveryOrchestrator.start()` (src/media_catalog/discovery/orchestration.py)
  accepts exactly one of url/post/account; `file` only rides a URL seed.
- `SeedMaterializationService.materialize` validates every URL resolves to a
  platform post identity and creates a stub post — legitimate for URL seeds
  (the URL already yields platform + native id), impossible for files
  (`posts.platform_id` is NOT NULL; inventing a synthetic platform pollutes
  the registry and the doctor).
- Query material is already strategy-keyed:
  `candidate_lookup/planning.py` builds
  `dict[LookupStrategy, list[LookupQueryMaterial]]` from post rows
  (`_post_materials`) or account rows (`_account_materials`). The post is
  only one extraction source; providers never see it.
- Sessions plan steps exactly once from seed material; hit results are
  persisted (proven by the 21-URL batch) but never re-read as material.
- Steps carry a (source, method) identity; sessions carry request and
  wall-clock budgets with per-step failure containment.

## Goals / Non-Goals

- Goals: a first-class local-file root with no synthetic identity; the
  exact-hash first hop; bounded two-generation follow-up that turns one hit
  into a fan-out within the same session; additive reporting.
- Non-Goals: perceptual-hash or visual matching (bead `qi7`); arbitrary-depth
  recursion; hash queries on providers without captured wire contracts
  (sankaku, pawchive — deferred until live-captured); changing URL/post/
  account seed semantics; external-index adapters (P0.2 external half).

## Decisions

### D1: file seeds are their own table, not posts

New `discovery_file_seeds` (migration): session-scoped row holding verified
md5/sha256, width/height/mime/byte_size when derivable, source path (operator
metadata, redacted from reports like other private paths), note, observed_at.
`discovery_sessions.input_kind` gains `local_file`; `input_digest` references
the seed row. Rationale: `posts.platform_id NOT NULL` makes the alternative a
lie; the seed's identity is intrinsic evidence, not a hypothesized remote
post. Hashes are computed by the service (never trusted from the caller or
the filename), reusing the seeding service's existing file validation
(size ceiling, regular-file checks).

### D2: material extraction extends, not replaces

Add `_file_materials(connection, file_seed_id)` beside
`_post_materials`/`_account_materials`, returning
`LookupQueryMaterial(VERIFIED_MD5, [md5])` (sha256 kept as seed evidence only;
no provider strategy consumes it). The planner branches on input kind for
extraction exactly as it branches for post/account today. The md5 is
`verified_` (we hashed the bytes) not `declared_` — the distinction the
strategy vocabulary already encodes.

### D3: first hop reuses the lookup machinery verbatim

Generation-one provider steps are ordinary `CandidateLookupService` steps
with `verified_md5` material against danbooru (`md5:` metatag), e621
(`md5:`), gelbooru DAPI — only where the adapter's captured contract supports
the query; providers without a captured hash contract report excluded
naming the missing capability (r4y: no speculative probes). A hit schedules
a `FETCH_POST` step (existing adapter operation) so the full record — source
URLs, external references, declared hashes — is normalized and persisted
before any material is extracted from it.

### D4: generations are a loop over existing plan/execute, depth-capped

After each provider generation, collect posts persisted by this session's
fetch steps, run `_post_materials` on them, plan follow-ups (source-link
fetch via the existing link resolver; `external_post_id` reverse lookups;
artist strategies in their established strength order), and skip any step
whose (source, method, normalized-target) identity already exists in the
session. Hard cap: two provider generations. Budgets apply across the whole
session as today; exhausted budgets leave remaining steps reported as
planned. No while-loop over results — an explicit `for generation in (1, 2)`.

### D5: reporting is additive

`report()` gains a `generations` field: per generation, the step list with
outcomes. Existing keys unchanged; re-reporting a session reproduces the same
values.

## Risks / Trade-offs

- Wire contracts for md5 queries may not be captured for every in-scope
  provider (gelbooru DAPI md5 semantics). Mitigation: implement against the
  existing adapter query builders; capture fixtures live before enabling a
  provider's hash hop; excluded-with-reason is an acceptable first ship for
  uncaptured providers.
- Generational re-extraction could surprise budgets on hit-rich posts.
  Mitigation: the depth cap plus existing per-step containment and budgets;
  the report names what stayed planned.
- File-seed rows without posts mean lookup/report code paths that assumed a
  seed post must handle its absence; the planner's excluded-with-reason
  pattern already models missing material.

## Migration Plan

One additive migration (next number in sequence): create
`discovery_file_seeds`; widen `discovery_sessions.input_kind` CHECK to
include `local_file`. No rebuilds: `input_kind` CHECK widening on
`discovery_sessions` follows the established CHECK-rebuild pattern only if
the column is CHECK-constrained — verify at implementation; prefer a new
nullable column over a rebuild if not.

## Open Questions

- None blocking. Gelbooru DAPI md5 wire shape resolved at implementation via
  live capture; sankaku/pawchive stay excluded until captured.
