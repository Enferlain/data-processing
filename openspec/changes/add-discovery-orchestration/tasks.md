# Tasks

- [x] 1. Migration `0024`: `discovery_sessions` + `discovery_steps` with run
      linkage; writer/reader support.
- [x] 2. `media_catalog.discovery.orchestration` module: session/step model, input normalization
      (seed materialization reuse + existing-record seeds), planner (local steps +
      per-provider strategy steps with exclusion reasons), runner (local SQL inline,
      provider steps via `CandidateLookupService` under `--live`, per-step failure
      containment, session budget).
- [x] 3. CLI `catalog discover`: input flags, `--live`, `--json`, budget flags,
      `--session <id>` re-report.
- [x] 4. Tests: input normalization idempotence and validation; planner
      availability/exclusion/skip matrix over real capabilities; local step SQL
      against seeded catalogs; runner with fake provider service (planned/complete/
      failed containment, budget enforcement); CLI surface; session re-report.
- [x] 5. Gates: ruff, format, ty, full pytest; reviewer; changelog; bead close and
      archive.
