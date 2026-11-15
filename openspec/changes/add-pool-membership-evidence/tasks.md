# Tasks

- [x] 1. Queue family `pool_member` over `post_pool_observations`
  (platform-scoped co-membership, availability-filtered, deduped), placed
  after `provider_parent`.
  Verify: `uv run pytest tests/test_pool_membership.py`.
- [x] 2. Tests pinning the spec scenarios: within-platform enqueue,
  cross-platform same-id never pairs, labeled pairs never re-enqueue, queue
  building writes no verdicts.
  Verify: `uv run pytest tests/test_pool_membership.py`.
- [ ] 3. Gates and docs: full pytest, ruff + format on changed files,
  `ty check src`, CHANGELOG entry, media-catalog labeling docs note.
- [ ] 4. Real-catalog smoke once the crosscheck loop exits: confirm
  `pool_member` pairs appear from the 145 existing observations.
- [ ] 5. Later slice (separate follow-up): danbooru `SEARCH_POOLS` discovery
  by artist name + bounded `fetch_pool` runner; e621 `FETCH_POOL` support;
  `reprocess` backfill pass for older e621 raws.
