## 1. Materialization service

- [x] 1.1 Implement candidate materialization in `src/media_catalog/relationships/`
      (confirmed-only filter, fixed kind mapping with post-level and work-level endpoint
      resolution, target-resolution refusal, decision-row provenance, evidence top-up,
      deterministic-key idempotency); verify with service tests that a confirmed candidate
      produces exactly one reviewed relationship with evidence attached and a decision
      naming the candidate
- [x] 1.2 Verify refusals with typed reasons (pending/rejected state, unresolved kind,
      unresolved target reference, missing work anchor) leave no relationship and do not
      block other candidates; verify re-materialization creates nothing new but attaches
      missing evidence; verify candidates and their ledgers are byte-unchanged and the
      operation performs no network access (socket-blocked test)

## 2. CLI and documentation

- [x] 2.1 Add `catalog relationships materialize` (--candidate optional single-candidate
      mode, --json output); verify with a CLI test including the offline proof
- [x] 2.2 Document the command and kind mapping in `docs/tools/media-catalog.md`, record
      the change in `CHANGELOG.md`, and run the full gates (`uv run ruff check .`,
      `uv run ruff format --check`, `uv run ty check src`, `uv run pytest`)
