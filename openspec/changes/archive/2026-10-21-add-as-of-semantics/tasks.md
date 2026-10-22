## 1. Vocabulary and spec

- [x] 1.1 Write `docs/plans/temporal-semantics.md` (five-timestamp vocabulary table mapped
      to columns, as-of reconstruction rules, availability-in-timelines rule, and the named
      follow-on surfaces); verify the doc cross-links the kernel plan, the export spec, and
      the reprocess contract
- [x] 1.2 Kernel and export spec deltas validated (`openspec validate`)

## 2. Projection as-of surface

- [x] 2.1 Add `as_of` to the projection spec object (participating in `spec_digest`),
      thread it through plan/run services and manifests, and add `--as-of` to the export
      CLI (refused for kinds without as-of semantics); verify with tests that every kind's
      manifest records the cutoff and that differing cutoffs change the spec digest
- [x] 2.2 Implement the cutoff filter in `field_sources` (observations with
      `observed_at <= cutoff`, current re-resolved within the restricted set); verify with
      fixture tests: a cutoff between two observations yields the earlier value alone, a
      cutoff after all observations matches the uncutoff values, a cutoff before all
      observations yields empty histories with counted exclusions intact

## 3. Closeout

- [x] 3.1 Document as-of in `docs/tools/media-catalog.md` (the flag, the manifest field,
      which kinds support it), record the change in `CHANGELOG.md`, update bead
      `data-processing-2ai` notes, and run the full gates (`uv run ruff check .`,
      `uv run ruff format --check`, `uv run ty check src`, `uv run pytest`)
