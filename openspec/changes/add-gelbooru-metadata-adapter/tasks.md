## 1. Research and Fixture Gate

- [x] 1.1 Add a credential-safe fixture capture utility for explicit Gelbooru DAPI JSON and single-post HTML requests that enforces response-size and time limits, records transport/parser versions, strips credential-bearing request material, and never requests media bytes.
- [x] 1.2 Capture and redact DAPI and HTML metadata fixtures for Gelbooru posts `12370900`, `11605534`, `10720246`, `10791439`, and `10791440`, preserving enough structure to cover the exact and user-labelled variation examples in `docs/plans/test_list.md`.
- [x] 1.3 Add minimal fixtures for DAPI tag responses and for missing credentials, 401, 403 or challenge, 404/unavailable, 429 or provider retry information when observed, 5xx, oversized bodies, and malformed JSON/HTML without committing credentials, private request URLs, or media bytes.
- [x] 1.4 Document the reviewed fixture contract: request shapes, response envelopes, field presence and types, pagination behavior, native tag-category evidence, returned media variants, status mapping, conservative pacing, retry headers, redaction decisions, and every unresolved provider assumption.
- [x] 1.5 Add characterization tests for the existing Danbooru, AIBooru, and e621 adapter/sync seams that Gelbooru integration will share, so provider-neutral refactoring cannot silently change their requests, continuations, normalized records, or public results.

## 2. Provider Configuration and Shared Transport Contract

- [x] 2.1 Add a dedicated Gelbooru provider package with immutable provider, adapter, schema, DAPI transport, HTML parser, and continuation versions; canonical HTTPS endpoints; a maximum DAPI page size of 100; finite body limits; and a conservative configurable pacing floor justified by the fixture review.
- [x] 2.2 Implement external `GELBOORU_USER_ID` and `GELBOORU_API_KEY` resolution as an all-or-nothing credential pair with redacted representations and failure before network access when configuration is absent or partial.
- [x] 2.3 Extend provider request, raw-provenance, and resume material with an explicit transport key/version while preserving the stable behavior and stored identities of existing providers.
- [x] 2.4 Ensure query-parameter credentials are injected only at the final DAPI HTTP boundary and sanitize transport exceptions, durable request attempts, raw-observation metadata, diagnostics, human output, and JSON output against credential values and rendered authenticated URLs.
- [x] 2.5 Audit the existing neutral schema and Gelbooru platform seed against proven fixtures; add only the smallest provider-neutral migration needed for a demonstrated gap, with fresh-schema, upgrade, rollback, foreign-key, trigger, ID-preservation, doctor, and immutability tests.

## 3. Credentialed JSON-DAPI Adapter

- [x] 3.1 Implement explicit DAPI request rendering for positive numeric post fetches, exact tag metadata supported by the fixture contract, and bounded post listings using `json=1`, `pid`, and a provider-capped `limit`, without undocumented alias, artist, pool, favorite, count, or deleted-stream endpoints.
- [x] 3.2 Implement typed DAPI response handling for success, missing or invalid credentials, authorization or challenge denial, unavailable records, rate limiting, transient provider failures, oversized bodies, and malformed or unsupported response shapes.
- [x] 3.3 Normalize fixture-proven DAPI post identity, timestamps, availability, source, uploader role, rating, score, declared MD5, dimensions, tag spellings/native category evidence, and returned media representations without deriving URLs or inferring authorship.
- [ ] 3.4 Implement target-, query-, sort-, transport-, direction-, boundary-, and version-scoped DAPI continuations; validate compatible resume before network access and pause before an unadmitted request, page, record, byte, or elapsed-time boundary.
- [x] 3.5 Add focused injected-transport tests for exact request shapes, the provider page ceiling, typed outcomes, response-first raw retention, continuation validation, committed-page resume, retry-attempt history, idempotent normalization, and zero media-host requests.

## 4. Anonymous Single-Post HTML Adapter

- [x] 4.1 Implement an explicit HTML transport that accepts one positive numeric post ID and performs exactly one bounded HTTPS request to the canonical Gelbooru post page, with no login, cookies, browser automation, scripts, listings, notes, sources, thumbnails, or media requests.
- [x] 4.2 Implement a small versioned HTML parser for only fixture-proven stable markers, including post identity and available source, uploader, rating, score, hash, dimensions, tag-category classes, and returned original/sample/preview references.
- [x] 4.3 Fail closed when identity markers are missing, markup is incompatible, a challenge page is returned, or field bounds are exceeded; retain the admitted raw HTML and report a typed outcome without switching to DAPI.
- [x] 4.4 Add focused tests proving one-response behavior, canonical request identity, bounded parsing, unavailable/challenge/malformed handling, category preservation, no secondary requests, no media access, and no credentials or cookies.

## 5. Normalized Persistence and Reconciliation

- [x] 5.1 Wire Gelbooru normalized pages through the shared response-first remote executor and page writer so raw response retention precedes normalization and normalized records, origins, budgets, and checkpoints commit atomically.
- [x] 5.2 Persist DAPI and HTML observations under the same Gelbooru numeric post identity while retaining separate raw observations, transport/parser versions, request attempts, timestamps, and provider assertions.
- [x] 5.3 Preserve uncategorized DAPI tags as native spelling with neutral `unknown`, map HTML categories only where fixtures prove them, keep uploader distinct from artist/creator attribution, and create no liked or bookmarked activity.
- [ ] 5.4 Define and test the current-projection policy for partial or disagreeing DAPI and HTML observations so omission never erases retained history and mutable disagreements remain auditable through raw provenance.
- [ ] 5.5 Verify that normalized returned media URLs remain browseable metadata-only variants, declared MD5 remains a provider assertion until local verification, and synchronization creates no assets or acquisition attempts.

## 6. CLI and Offline Inspection

- [ ] 6.1 Add explicit metadata CLI routes for Gelbooru DAPI post, bounded DAPI listing, supported exact tag metadata, and HTML single-post fetches; require the transport in command selection and never silently fall back.
- [ ] 6.2 Route DAPI commands through external credential resolution and provider pacing, route HTML commands without credentials, and preserve shared request/page/record/time limits plus compatible `--resume-from` only where continuations are supported.
- [ ] 6.3 Add stable human and JSON result tests covering run IDs, transport identity, typed outcomes, budget boundaries, resume lineage, and bounded diagnostics while excluding query material, credentials, raw payloads, private paths, and returned media URLs.
- [ ] 6.4 Extend offline remote-run, post, and media-occurrence inspection tests to show Gelbooru identities, declared versus observed facts, provenance, and stable variant selectors without opening raw payloads or media.

## 7. Acceptance, Regression, and Policy Tests

- [ ] 7.1 Add a default-offline acceptance matrix for all five real Gelbooru post IDs across every available captured transport, including the three user-labelled variation records, and assert stable post reconciliation plus independent observation history.
- [ ] 7.2 Add privacy and network-isolation tests that scan the catalog, public result objects, errors, logs, and fixtures for credential sentinels and prove metadata runs contact only the explicitly selected Gelbooru endpoint.
- [ ] 7.3 Add budget, interruption, transaction rollback, database reopen, resume, duplicate-observation, malformed-response, and transport-mismatch tests using real catalog persistence and injected HTTP transports.
- [ ] 7.4 Run provider regression suites for Pixiv, Danbooru, AIBooru, and e621 metadata, lookup, library, browsing, and acquisition boundaries to prove Gelbooru support does not declare or trigger unrelated capabilities.
- [ ] 7.5 Add disabled-by-default, explicitly authorized live smoke tests for one DAPI post and one HTML post with hard request/body/record/time limits, external credentials for DAPI, policy acknowledgement, and assertions that no media host is contacted.

## 8. Documentation and Finalization

- [ ] 8.1 Document Gelbooru DAPI and HTML usage, external credential setup, transport selection, pacing and page limits, provenance, raw-versus-normalized behavior, privacy, typed failures, resume limits, and troubleshooting.
- [ ] 8.2 Document Gelbooru's current automation-policy risk and require the operator to confirm personal-use or other authorization before live use; state that credentials do not grant permission and that scheduled or recursive crawling is not provided.
- [ ] 8.3 Update the roadmap, changelog, provider capability matrix, and real-example test plan to distinguish implemented metadata from deferred lookup, library expansion, acquisition, aliases, pools, favorites, counts, deleted streams, similarity, and cross-database matching.
- [ ] 8.4 Run `uv run ruff format --check` on changed Python files, `uv run ruff check .`, `uv run ty check src`, the focused Gelbooru suites, the full test suite, `git diff --check`, and strict OpenSpec validation; then request bounded review of each completed implementation section and address actionable findings before sync/archive.
