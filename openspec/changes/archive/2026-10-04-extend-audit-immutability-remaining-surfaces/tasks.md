## 1. Migration and tests

- [x] 1.1 Write `src/media_catalog/migrations/0013_audit_immutability_completion.sql`: no-delete
  triggers for `library_expansion_plans`, `library_expansion_probes`,
  `library_expansion_executions`, `library_expansion_posts`, `candidate_lookup_requests`, `media_acquisition_attempts`;
  no-update and no-delete for `media_acquisition_verifications` and `raw_payloads`; and
  PK-guarded recreations of the 0006/0007 immutable-inputs triggers — verify fresh creation and
  the upgrade path (`uv run pytest tests/test_catalog_database.py
  tests/test_remote_transport_identity.py tests/test_e621_neutral_schema.py`)
- [x] 1.2 Extend `tests/test_kernel_storage_enforcement.py` with seed rows for the new surfaces
  and tests asserting every blocked mutation (update and delete where applicable), plus
  no-op/state-advance passthroughs for the recreated triggers
- [x] 1.3 Run the full gates (`uv run pytest`, `uv run ruff check .`, `uv run ty check src`) and
  confirm they pass with no new exclusions

## 2. Docs and close-out

- [x] 2.1 Extend the `CHANGELOG.md` `[2026-10-04]` entry with the completion migration, remove
    the kernel plan's deletion-guard caveat, and update the roadmap current-state sentence
- [x] 2.2 Close Bead `data-processing-5de`, run `openspec validate
    extend-audit-immutability-remaining-surfaces --strict`, sync the delta spec into the main
    specs, archive the change, and verify `openspec list` is empty and `openspec validate
    --specs` passes
