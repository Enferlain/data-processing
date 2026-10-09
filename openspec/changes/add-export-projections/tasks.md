## 1. Projection framework

- [ ] 1.1 Create `src/media_catalog/projections/` with the projection-spec object (kind,
      schema version, six policy slots, tool/source versions), canonical-JSON digest helpers,
      and the stable-identifier selection digest; verify with unit tests that the spec digest
      is stable across equal specs, moves on any policy change, and excludes the generation
      timestamp
- [ ] 1.2 Implement the manifest builder (spec, generation timestamp, per-file row counts and
      content digests, inclusion/exclusion counts with bounded reasons) and the shared privacy
      guard (allowlist enforcement, URL query stripping); verify with unit tests that a field
      off the allowlist is rejected and URLs emit origin+path only
- [ ] 1.3 Implement the row pipeline with JSONL and CSV serializers from one row sequence
      (deterministic column order, nested values as canonical JSON strings); verify with a
      unit test that JSONL and CSV rows are logically equivalent

## 2. Projection kinds

- [ ] 2.1 Implement the `assets` projection (one row per verified asset: content identity,
      verified byte/image facts, representation-link count, bounded legacy-assertion
      classification; ordering by asset id); verify exact-duplicate collapse and
      representation counts with a fixture database test
- [ ] 2.2 Implement the `posts` projection (platform identity, current mutable facts with
      evidence pointer, occurrence summary, participant summary with roles and review states;
      ordering by post id); verify participant review states appear without overriding any
      decision
- [ ] 2.3 Verify with an integration test on a shared fixture catalog that re-running either
      projection reproduces identical spec/selection digests and logically equivalent rows,
      and that evidence change (an inserted row) moves the selection digest

## 3. Service and CLI

- [ ] 3.1 Implement the projection service `plan` (read-only: policy echo, would-be counts,
      exclusion reasons, no files) and `run` (writes data files plus manifest under an
      operator directory, enforcing the row limit with `excluded_by_limit` reporting); verify
      with tests that plan writes nothing and run bounds output
- [ ] 3.2 Add the `catalog export plan|run` command group (kind, format, limit, out-dir
      arguments, `--json` output) and a CLI test proving network access is never attempted
      and the catalog is unmodified by a run

## 4. Verification and documentation

- [ ] 4.1 Add privacy regression tests over a catalog containing storage paths and
      query-bearing URLs: no exported row or manifest field contains a path or query string;
      verify with the full test file run
- [ ] 4.2 Document the export surface in `docs/tools/media-catalog.md` (commands, manifest
      reading, policy meanings, limits) and record the change in `CHANGELOG.md`; verify docs
      links resolve and gates pass (`uv run ruff check .`, `uv run ty check src`,
      `uv run pytest`)
