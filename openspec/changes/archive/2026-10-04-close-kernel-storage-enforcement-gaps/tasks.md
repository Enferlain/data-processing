## 1. Migration

- [x] 1.1 Write `src/media_catalog/migrations/0012_kernel_storage_enforcement.sql` with the
  audited triggers: no-update/no-delete for `raw_observations`, `post_tag_observations`,
  `observation_revisions`, `account_candidate_decisions`, `post_candidate_decisions`; no-delete
  for `observations`, `adoption_attempts`, `account_match_candidates`, `post_match_candidates`,
  `match_evidence`, `account_candidate_evidence`, `post_candidate_evidence`; conditional
  column-immutability plus no-delete for `remote_requests`; immutable-inputs for `remote_runs` —
  and verify fresh creation applies it (`uv run pytest tests/test_catalog_database.py`) and the
  upgrade path migrates cleanly (exercised by the versioned suites, e.g.
  `uv run pytest tests/test_remote_transport_identity.py tests/test_e621_neutral_schema.py`)

## 2. Enforcement tests

- [x] 2.1 Add trigger tests asserting every blocked mutation aborts with a table-naming message
  (update and delete on insert-only tables and decisions; delete on candidates, evidence, and
  join tables; non-attach updates and deletes on `remote_requests`; input-column changes on
  `remote_runs`), using the `pytest.raises(sqlite3.IntegrityError, match=...)` idiom
- [x] 2.2 Add legitimate-path tests proving the audited mutations still work under the triggers
  via direct SQL on the same columns the finish/review writers use — remote-run state advance,
  remote-request raw-observation attach (including retry-safe re-attach), a provenance-event
  current-projection refresh, and candidate/evidence current-field updates — with the writer
  paths themselves covered by the existing suite in 2.3
- [x] 2.3 Run the full gates (`uv run pytest`, `uv run ruff check .`, `uv run ty check src`) and
  confirm they pass with no new exclusions — any failure names a write path the audit missed,
  which is rescoped deliberately rather than silently dropped

## 3. Docs and close-out

- [x] 3.1 Add a `CHANGELOG.md` entry under the current date covering the enforcement migration
    and the purge-consequence note, following the file's concision rules
- [x] 3.2 Update `ROADMAP.md` current state and the kernel plan's section 2 enforcement bullet
    (append-only now storage-enforced for the listed tables), close Bead `data-processing-ts5`
    with `--suggest-next`, and record follow-ups if the gates exposed any rescoped trigger
- [x] 3.3 Run `openspec validate close-kernel-storage-enforcement-gaps --strict`, sync the delta
    spec into the main specs, archive this change via the OpenSpec archive workflow, and verify
    `openspec list` shows no active change and `openspec validate --specs` passes afterwards
