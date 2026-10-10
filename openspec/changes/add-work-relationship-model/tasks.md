## 1. Schema

- [ ] 1.1 Write the migration creating `works`, `work_representations`, `relationships`,
      `relationship_evidence`, `relationship_review_decisions`, and
      `relationship_status_history` with the closed kind vocabulary and immutability triggers
      per tier (works/links insert-only; relationships current-field-updates-only; evidence
      links, decisions, transitions fully immutable); verify with migration tests that
      UPDATE/DELETE are rejected per tier and permitted updates only touch status fields
- [ ] 1.2 Add the relationship records layer (validation of endpoint kinds per relation kind,
      symmetric/directional orientation, canonical relationship_key computation) to the
      persistence writes; verify with unit tests that orientation is canonicalized, keys are
      deterministic, and invalid endpoint-kind pairings are rejected

## 2. Works and seeding

- [ ] 2.1 Implement work materialization (one work per post with occurrences, linked
      representations, work_kind from occurrence count) with idempotent re-runs; verify a
      post with three occurrences yields one work linked to all three and re-running changes
      nothing
- [ ] 2.2 Implement the deterministic seeder for `same_bytes` (occurrence pairs sharing a
      verified asset), `thumbnail_of` (sample/preview role toward the post's original), and
      `reposted_from` (source-URL references resolving to another post), each attaching
      evidence rows (detector + version, stance supports) and reporting materialized/existing/
      skipped counts with reasons; verify idempotency, evidence citation, and that no
      identity/authorship/same-work conclusion is materialized
- [ ] 2.3 Prove the seeder is offline (socket-blocked test) and that it never writes the
      evidence layer it reads

## 3. Review lifecycle

- [ ] 3.1 Implement relationship review (confirm/reject/reverse decisions, append-only ledger
      with prior state, review_state follows latest decision, rejected rows retained) and
      status transitions (append-only history, e.g. observed → reviewed); verify the
      confirm-then-reverse scenario keeps both decisions, all evidence, and one row

## 4. Queries, projection, CLI

- [ ] 4.1 Add relationship and work query surfaces (list/filter by kind, status, endpoints)
      returning privacy-safe rows; verify endpoint resolution and filtering with tests
- [ ] 4.2 Add the `works` export projection kind (representations with roles and verified
      hashes, preferred-representation policy excluding thumbnail/preview roles and preferring
      the original role, same_work summary) with stated manifest policies; verify the
      thumbnail-exclusion and digest-reproduction scenarios against a fixture catalog
- [ ] 4.3 Add the CLI commands (`works materialize`, `relationships seed|list|review`, export
      kind `works`) with `--json` output; verify the CLI test covers seeding offline and
      review round-trip

## 5. Verification and documentation

- [ ] 5.1 Run the full gates (`uv run ruff check .`, `uv run ty check src`,
      `uv run pytest`) and fix findings
- [ ] 5.2 Document works/relationships in `docs/tools/media-catalog.md` (decision-table
      summary, seeding, review, works export), record the change in `CHANGELOG.md`, and update
      the roadmap milestone state; verify docs links resolve
