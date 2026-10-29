# Tasks

## 1. Instance machinery

- [x] 1.1 Generalize `GelbooruInstance`: replace the `platform_key == PROVIDER_KEY` lock with lowercase-slug validation plus the `GELBOORU_INSTANCES` family registry, and add `dapi_credentials_required: bool = True`
- [x] 1.2 Ship `SAFEBOORU` (safebooru.org: platform key `safebooru`, canonical HTTPS base, `safebooru-json-v1` dapi schema version, `dapi_credentials_required=False`) and the `GELBOORU_INSTANCES` registry
- [x] 1.3 Parameterize `GelbooruAdapter`/`GelbooruHtmlAdapter` credential enforcement by instance policy (raise before network only when required and absent; HTML stays gelbooru-only)


## 2. Kernel registration and capture
- [x] 2.1 Register `safebooru` in `SOURCE_OPERATIONS` and update the adapter-contracts registry test's pinned key set
- [x] 2.2 Extend the capture utility to honor the instance credential policy (anonymous dapi captures allowed) and run a bounded live capture of one safebooru post plus the empty-notes/empty-result shape
- [x] 2.3 Build the safebooru fixture suite from the captured bytes (redacted, manifest with capture date and schema version); verify fixture contains no credential material
## 3. Surfaces

- [x] 3.1 Add `--instance {gelbooru,safebooru}` (default `gelbooru`) to the gelbooru dapi metadata and enrichment commands (HTML stays canonical-gelbooru, no flag); instance-aware credential guidance text
- [x] 3.2 Wire instance resolution through lookup/reprocess provider maps only where capabilities exist (no change while lookup is deferred)
- [x] 3.3 Tests: instance config validation, per-instance credential policy (required-raise, anonymous-proceeds), CLI flag routing, safebooru fixture-backed normalization and notes flow

## 4. Verification and close-out
- [x] 4.0 Review fixes (FamilyReviewer): migration `0020` seeds the `safebooru` platforms row (persistence resolves platform ids from it), the captured empty-notes bytes land as `safebooru_notes_7272295.xml` with a notes-flow test, notes-capture `parser_version` and `lookup_plan_context` derive from the instance, the spec delta gains the MODIFIED notes requirement scoping credentials per instance policy, `created_at` gates on key presence (explicit null is malformed), and `links.py` recognizes `safebooru.org`

- [x] 4.1 Full gates: `ruff check`, `ruff format` on changed files, `ty check src`, full `pytest`
- [x] 4.2 Reviewer subagent pass on the complete diff; address findings
- [x] 4.3 CHANGELOG entry under the current date
- [x] 4.4 Sync spec delta into `openspec/specs/gelbooru-metadata-adapter`, archive the change, close Bead `data-processing-x5w`
