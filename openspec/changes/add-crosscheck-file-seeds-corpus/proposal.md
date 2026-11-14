## Proposal

### What

Add a `file-seeds` corpus to `catalog crosscheck` so bare-file discovery seeds
(`discovery_file_seeds`, e.g. the 24,142 grabber-collection seeds from
`catalog ingest folder`) can be batch cross-checked across live providers exactly
like post corpora.

### Why

The crosscheck coordinator already handles file subjects — `run_crosscheck`
branches to `_file_materials` for non-post seeds, `crosscheck_items.seed_kind`
accepts `'file'`, `_reusable_run` keys on `seed_file_id`, and the planner parses
`file:ID` seeds — but no corpus can select them: `CORPORA` and `select_corpus`
only produce `post` subjects, and `crosscheck_batches.corpus` has a CHECK
constraint that rejects the new value. The grabber seeds carry verified md5
material (the only material a bare file has) and were ingested precisely so
discovery treats them uniformly; the batch runner is the missing wire.

### Scope

- `CORPORA` gains `file-seeds`; `select_corpus` returns canonical file-seed
  subjects (lowest id per verified hash pair, matching `find_file_seed_id`).
- Migration widens the `crosscheck_batches.corpus` CHECK (rebuild per the 0031
  CHECK-widening convention; existing batches and items preserved).
- CLI `--corpus` help text; spec delta; tests.

Out of scope: sidecar parsing for folder-ingested seeds, any new lookup
strategy, changing how matches materialize (they stay candidates).
