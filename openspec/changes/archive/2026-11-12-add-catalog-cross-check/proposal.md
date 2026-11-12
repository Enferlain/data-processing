## Proposal

Add `catalog crosscheck`: one first-class batch command that cross-checks a
selected catalog corpus across the configured supported providers, built on the
existing `CandidateLookupService`, retained lookup runs, and checkpoints. Durable
resume, item-level reporting, serialized writes, graceful stop.

## Why

Cross-checking the catalog today means one seed/provider at a time or agent-written
orchestration (bead `data-processing-p1t`). The real-data coverage pass showed the
actionable miss class precisely: 29% of the hash-material corpus (31 of 106 subjects)
does not exist in the e621 index — Danbooru/Gelbooru/AIBooru exact lookups already
implement the strategies that can resolve them; what is missing is batch coordination.
The prior ad-hoc live run (`jh3`) also exposed a real defect: concurrent provider
lookups deadlock SQLite (`OperationalError` at startup); the batch command must
serialize write transactions by construction.

## What Changes

- `catalog crosscheck <catalog>` with explicit corpus selection:
  `--corpus hash-material` (default: posts/files carrying md5 or foreign-id query
  material — the reviewed/downloaded focus successor), `--corpus downloaded` (posts
  with acquired assets), `--corpus all` (explicit opt-in; metadata-only bookmarks
  are named as such in reporting, never silently swept).
- Per (subject × provider × strategy): reuse a fresh complete lookup run
  (same seed revision + material digest + strategy version) instead of re-querying;
  `--recheck {unsearched,stale,force}` mirrors discovery policy.
- Budgets are checkpoint controls, not truncation: `--max-requests`, `--max-minutes`
  stop at item boundaries, finalize in-flight run state, preserve pages/checkpoints;
  a later invocation resumes pending items without restarting completed work.
- Writes are serialized in one process/connection (network pacing via existing
  adapter minimum intervals and retry-after); no cross-process writer contention.
- Item-level durable state (migration `0034`): batch header + per-item rows with
  state (checked / matched / pending / skipped / failed) and reasons; summary
  reports counts, matched candidates are recorded as provenance-preserving
  candidates only — never confirmed relationships.
- Missing credentials and provider rate limits surface as visible, resumable
  skipped/failed reasons.

## Out of Scope

- Network-level concurrency (multi-threaded providers) — v1 is sequential per
  provider; the serialized-write invariant is what the jh3 incident demands.
- Automatic relationship confirmation from matches.
- Index-side (offline) methods — those already run via `catalog discover`; this
  command is provider (live) cross-checking.
- Danbooru metadata-snapshot indexing (separate follow-up; not blocked, just not
  this).
