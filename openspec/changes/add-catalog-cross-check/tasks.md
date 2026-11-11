# Tasks: catalog crosscheck

## 1. Catalog state

- [ ] 1.1 Migration `0034_crosscheck_batches.sql`: `crosscheck_batches`
      (batch_key identity: corpus + providers + recheck policy; started/stopped
      counts; schema 34) and `crosscheck_items` (batch, subject post/file,
      provider, strategy, run_id, state machine, reason, matched_count).
- [ ] 1.2 CrosscheckStore: batch open/resume by key, item transitions, summary
      aggregation — all through the single writable connection.

## 2. Coordination engine

- [ ] 2.1 Corpus selectors: `hash-material` (non-empty material digest),
      `downloaded` (posts with acquired assets), `all`; subjects ordered
      deterministically.
- [ ] 2.2 Done-detection: complete run reuse keyed on (seed_revision,
      material_digest, strategy_version, adapter_version); recheck modes
      `unsearched|stale|force`.
- [ ] 2.3 Sequential executor over (subject × provider × strategy):
      plan/execute or resume via CandidateLookupService; retry-after surfaced;
      item-boundary budget checks; graceful stop finalizing in-flight state.
- [ ] 2.4 Skip reasons: reused / no-query-material / missing-credentials /
      provider-undeclared / rate-limited(retry_after) / provider-failed(reason).

## 3. CLI + reporting

- [ ] 3.1 `catalog crosscheck <catalog> [--corpus ...] [--provider ...]`
      `[--recheck ...] [--stale-after ...] [--max-requests N] [--max-minutes M]`
      `[--json]`; budget defaults conservative; resume by identical invocation.
- [ ] 3.2 Summary + per-item reporting (state counts by provider; metadata-only
      labeling; matched counts; candidate provenance pointer via run ids).

## 4. Verification

- [ ] 4.1 Integration tests: resume without re-running completed items; budget
      stop at item boundary with checkpoint; reused-run skip; rate-limit
      visibility; serialized writes (single connection asserted); no
      relationship/pair rows created.
- [ ] 4.2 Real-data bounded run against the actual catalog: `--corpus
      hash-material --max-requests` small, then measure what the e621-index
      md5-miss subjects turn into on Danbooru/Gelbooru/AIBooru.
- [ ] 4.3 Docs (`docs/tools/`), CHANGELOG.
