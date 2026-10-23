## Why

Live danbooru post payloads carry no pool ids (verified on retained raw 12320097), so pool
observations cannot come from post sync — pool grouping is the remaining danbooru gap for
work-grouping evidence (Bead `data-processing-cq0`, split from `data-processing-unp`). Pools are
ordered post sequences (often series); their ordering is exactly the work-grouping signal the
kernel wants as evidence, never as an automatic conclusion.

## What Changes

- Add `fetch_pool` to the closed adapter/run operation vocabularies (`AdapterOperation`,
  `REMOTE_OPERATIONS`) — a media-family vocabulary addition in the kernel's existing pattern, not a
  vocabulary generalization.
- Danbooru adapter: `FETCH_POOL` request path (`GET /pools/{id}.json`, single object, no
  pagination — the requirement's resumable semantics apply where an endpoint paginates, and this
  one does not).
- A bounded pool sync surface (`src/media_catalog/remote_sync/pools.py`): remote run with declared
  budgets, remote request, raw report retention with provenance, typed outcome — the standard run
  contract over a non-post object kind.
- Migration: `pool_observations` (pool-scoped facts, observation digest over the ordered membership
  so unchanged pools re-observe idempotently and reorderings land as new observations) and
  `pool_member_observations` (position + post native id always retained; post id linked only for
  already-retained posts) — storage-immutable from the first migration.
- Post-view membership through the existing `record_post_pool` for retained posts; pool membership
  claims no work-grouping conclusion and creates no relationship rows — Phase D relationship
  conclusions stay review-gated as specified.
- CLI: `mcat remote pool-fetch --provider danbooru --pool-id N`.
- Fixtures (one real captured pool document) and tests; danbooru-family spec delta.

## Capabilities

- **New Capabilities:** none.
- **Modified Capabilities:**
  - `danbooru-family-metadata-adapter` — new requirement: bounded, ordered, evidence-only pool
    collection with scenarios for ordering retention, unretained members, digest idempotency, and
    the no-automatic-conclusions boundary.

## Impact

- `src/media_catalog/adapters/contracts.py` (operation enum), `src/media_catalog/records/common.py`
  (`REMOTE_OPERATIONS`), `src/media_catalog/adapters/danbooru/adapter.py` (request path),
  `src/media_catalog/remote_sync/pools.py` (new), `src/media_catalog/migrations/0016_pools.sql`
  (new), records + persistence + writer facade for pool observations, `src/media_catalog/cli.py`,
  `tests/` (fixture + test module), `CHANGELOG.md`, surface digests in
  `tests/test_persistence_compatibility.py` (conscious update: new records/writer surface).
- The kernel-consumer spike's F2 finding (`data-processing-6y1`) concerns *non-media* reuse of the
  operation vocabulary; this change grows the vocabulary for the media family, which that decision
  does not block.
