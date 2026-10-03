## 1. Provider-path proof (fixture-first)

- [x] 1.1 Add Danbooru attribution checkpoint/resume expansion coverage with injected fixtures —
  planning, execution, pause, resume without duplicated or skipped pages — extending the existing
  metadata-adapter fixture suites with listing/cursor pages where needed, and verify with focused
  pytest coverage
- [x] 1.2 Add AIBooru attribution execution and checkpoint/resume expansion coverage with
  injected fixtures and verify with focused pytest coverage
- [x] 1.3 Add a per-provider expansion matrix test mirroring `tests/test_e621_library_matrix.py`
  that walks every registered capability through planning, execution, checkpoint, and resume —
  confirming the existing Pixiv `next_url` pause/resume coverage holds — and verify it passes for
  all four providers
- [x] 1.4 Run the full gates (`uv run pytest`, `uv run ruff check .`, `uv run ty check src`) and
  confirm they pass with no new exclusions; if a provider proves unimplementable within the
  contracts, register it as unsupported with a bounded reason instead

## 2. Reviewed-target resolution and capabilities view

- [x] 2.1 Extend offline target resolution — which already resolves confirmed identity member
  accounts and explicit stable selections — to report each candidate's review state and surface
  pending/rejected candidates as ineligible instead of silently filtering them, and verify with
  tests covering confirmed, reversed, pending, and explicit-selection cases plus a no-network
  assertion
- [x] 2.2 Add the `catalog library capabilities` view (provider, capability key and version,
  operation, adapter/schema versions, unsupported markers with reasons) with structured JSON
  output, and verify with CLI tests including a supported-attribution case and an
  unsupported-provider case

## 3. Expansion-scoped acquisition selection

- [x] 3.1 Extend acquisition planning to resolve selections from a committed expansion plan's
  associations under the fixed criteria (variant, availability, eligibility, item limit), reporting
  inclusions and by-limit and `details_required` exclusions offline, and verify with planning
  tests asserting zero media requests and unchanged explicit-selection behavior
- [x] 3.2 Add `catalog assets download-plan --library-plan` CLI selection and verify with CLI
  golden tests that the produced plan matches an equivalent explicit `--select` plan

## 4. Docs and close-out

- [x] 4.1 Add the reviewed-target workflow walkthrough to the `catalog` tool guide
    (`docs/tools/media-catalog.md`)
- [x] 4.2 Add a `CHANGELOG.md` entry under the current date covering the workflow, following the
    file's concision rules
- [x] 4.3 Update `ROADMAP.md` current state, close Bead `data-processing-iso` with
    `--suggest-next`, and record any follow-up beads (for example contract drift or unsupported
    providers)
- [x] 4.4 Run `openspec validate generalize-reviewed-target-workflow --strict`, sync the delta
    specs into the main specs, archive this change via the OpenSpec archive workflow, and verify
    `openspec list` shows no active change and `openspec validate --specs` passes afterwards
