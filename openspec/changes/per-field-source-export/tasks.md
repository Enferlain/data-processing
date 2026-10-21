## 1. Projection kind

- [ ] 1.1 Implement `src/media_catalog/projections/field_sources.py` (per-post row,
      per-field nested history with newest-observation-wins current, non-null assertion
      entries, fixed field vocabulary) and register the kind in the service and CLI choices;
      verify with fixture tests that dissenting values are all retained and the newest
      observation's value is marked current
- [ ] 1.2 Verify exclusions and contract conformance with tests: posts without retained
      observations excluded with a counted reason, limit overflow counted, digest
      reproduction on unchanged evidence, no allowlist violations, no URLs or payload
      content, and the run writes nothing

## 2. Documentation and closeout

- [ ] 2.2 Document the kind in `docs/tools/media-catalog.md`, record the change in
      `CHANGELOG.md`, close bead `data-processing-1oi` with the slice delivered, and run
      the full gates (`uv run ruff check .`, `uv run ruff format --check`,
      `uv run ty check src`, `uv run pytest`)
