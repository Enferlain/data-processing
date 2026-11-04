# Tasks

- [x] 1. Schema: migration adding `discovery_file_seeds` (verified md5/sha256,
  width/height/mime/byte_size, path, note, observed_at) and the
  `local_file` input kind on `discovery_sessions`; working catalog patched.
- [x] 2. Seeding: file-only materialization in the seeding service — compute
  md5/sha256 + probe dimensions/mime (size ceiling, regular-file checks,
  bounded diagnostics); no posts row, no platform identity; path redaction in
  reports.
- [x] 3. CLI: `discover --file <path>` standalone in the mutually exclusive
  input group (still attachable to `--url`); input kind `local_file`;
  budget flags unchanged.
- [x] 4. Material: `_file_materials` extractor returning
  `verified_md5` material; planner branch for file seeds — local md5 search
  executes offline; `local_source_url`/`local_platform_identity` excluded
  naming missing material.
- [x] 5. First hop: provider `verified_md5` steps via the existing lookup
  service for providers with captured hash-query contracts; uncaptured
  providers excluded naming the capability; hit schedules a `FETCH_POST`
  step through the existing sync path.
- [x] 6. Wire capture: verified_md5 was already a fixture-contracted capability
  on all four providers (doctor 11/11 green); the live acceptance run exercised
  every wire end-to-end and its payloads are retained in the recorded lookup
  runs (45-55). No new fixture files were needed.
- [x] 7. Generations: depth-capped (2) follow-up planning from posts
  persisted by this session's fetch steps — `_post_materials` re-extraction,
  source-link fetch, `external_post_id` reverse lookups, artist strategies in
  strength order; step-identity dedupe; budgets apply across generations;
  exhausted budgets leave steps reported planned.
- [x] 8. Reporting: additive `generations` field on session reports;
  existing keys unchanged; re-report reproduces values without new requests.
- [x] 9. Tests: offline planner behavior for file seeds (planned/excluded
  honesty, no synthetic identity); replay tests for the hash hop using
  captured fixtures; generation tests (dedupe, depth cap, budget stop)
  offline with mocked provider steps; session re-report stability.
- [x] 10. Acceptance: run the Milestone A demonstration on
  `/mnt/e/Grabber/230bb8160ea5c6a90fc53e258cf8673e.jpg` with `--live`;
  whatever it yields (zero hits included) is the truth; record the run in the
  changelog.
- [x] 11. Gates: ruff, ruff format --check, ty, full pytest; reviewer pass;
  changelog; commit; close bead; archive change.
