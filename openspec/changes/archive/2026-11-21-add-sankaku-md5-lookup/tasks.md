# Tasks

## 1. Adapter capability surface

- [x] 1.1 `SankakuInstance`: declare `lookup_capabilities` (`DECLARED_MD5`, `VERIFIED_MD5`, result kind `post`, keyset, page size 100) and the `lookup_plan_context` property, mirroring `DanbooruInstance`
- [x] 1.2 `SankakuAdapter`: implement `fetch_lookup` (md5 strategies → existing `_listing_request` with `tags=md5:<hash>`; refuse other strategies before network) and `normalize_lookup` (envelope validation, `_post_items`-backed `NormalizedLookupResult` per post, continuation, page counts)

## 2. Crosscheck lane registration
- [x] 2.1 Add `"sankaku"` to `crosscheck.PROVIDERS` (CLI choices derive automatically)

## 3. Fixtures and tests

- [x] 3.1 Capture one live `tags=md5:<hash>` keyset response, redact, and register it in the sankaku fixture manifest
- [x] 3.2 Tests: capability declaration and plan-context; `fetch_lookup` md5 render + unsupported-strategy refusal + credential absence; `normalize_lookup` hit/miss/malformed via injected transport; crosscheck lane participation (item outcomes, budget/pacing paths) mirroring the existing md5-lane tests

## 4. Verification

- [x] 4.1 Gates: `uv run pytest`, `uv run ruff check .`, `uv run ruff format` on touched files, `uv run ty check src`
- [x] 4.2 Live opt-in smoke: `catalog crosscheck <catalog> --provider sankaku --max-requests 2` (bounded, credentials from the central env file)

## Workflow follow-up

- Archive the change (`openspec archive add-sankaku-md5-lookup`); sync the two delta specs
- Add CHANGELOG.md entry under Added
- Update bead `data-processing-hvs` (phase 1 shipped; phases 3–4 remain)
