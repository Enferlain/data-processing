# Tasks: catalog crosscheck

## 1. Catalog state

- [x] 1.1 Migration `0034_crosscheck_batches.sql` (schema 34).
- [x] 1.2 CrosscheckStore: batch open/resume by key, item transitions, summary
      aggregation — all through the single writable connection.

## 2. Coordination engine

- [x] 2.1 Corpus selectors: `hash-material`, `downloaded`, `all`.
- [x] 2.2 Done-detection: complete run reuse keyed on (provider, strategy,
      seed_revision, material_digest, strategy_version, adapter_version); recheck
      modes.
- [x] 2.3 Sequential executor with item-boundary budget checks and graceful stop.
- [x] 2.4 Skip/fail reasons incl. fresh-run-reused, no-query-material,
      rate-limited(retry_after).

## 3. CLI + reporting

- [x] 3.1 `catalog crosscheck` with corpus/provider/recheck/budget flags.
- [x] 3.2 Item-level durable state + summary (states by provider, reasons,
      matched counts).

## 4. Verification

- [x] 4.1 Integration tests: resume without re-running completed items; budget
      stop at item boundary; reused-run skip; rate-limit visibility; no
      relationship/pair rows created.
- [ ] 4.2 Real-data bounded run against the actual catalog: `--corpus
      hash-material --max-requests` small, then measure what the e621-index
      md5-miss subjects turn into on Danbooru/Gelbooru/AIBooru.
- [x] 4.3 Docs (`docs/tools/media-catalog.md`), CHANGELOG.
