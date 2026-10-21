## 1. Projection kind

- [x] 1.1 Implement `src/media_catalog/projections/attribution.py` (linked-pair selection
      over post-level relationships, attribution gathering from participants and
      tag-implied entities, confirmed-identity exclusion, name-match hint, per-relationship
      rows with exclusion reasons) and register the kind in the service and CLI choices;
      verify with fixture tests that an unjoined attributed pair over a seeded
      `reposted_from` link emits exactly one row with both identity lists and the hint
- [x] 1.2 Verify exclusions and contract conformance with tests: confirmed-identity join
      excludes the pair with a counted reason, missing attribution on an end excludes,
      rejected relationships exclude, the row limit reports `excluded_by_limit`, re-running
      reproduces digests, no allowlisted-field violations, and the run writes nothing to the
      catalog

## 2. Documentation and closeout

- [x] 2.1 Document the kind in `docs/tools/media-catalog.md`, record the change in
      `CHANGELOG.md`, update bead `data-processing-1oi` notes, and run the full gates
      (`uv run ruff check .`, `uv run ruff format --check`, `uv run ty check src`,
      `uv run pytest`)
