## 1. Contract Fixtures and Adapter Boundaries

- [x] 1.1 Add the `media_catalog.adapters` package structure, provider-neutral operation/response/page/continuation value types, typed outcome vocabulary, and adapter protocols without provider persistence or network side effects.
- [x] 1.2 Define a versioned fixture manifest and expected-normalization format that records provider, instance, capture date, redactions, adapter schema version, request identity, response status/headers, and expected records.
- [x] 1.3 Add minimal redacted fixtures for Pixiv profile, single-page artwork, multi-page artwork, Ugoira, artwork listing, restricted/deleted/authentication outcomes, and validate that no committed fixture contains credentials or media bytes.
- [x] 1.4 Add minimal redacted fixtures for Danbooru and AIBooru posts, artist records, categorized tags, uploader/source/Pixiv references, parent/child relations, keyset continuation, deleted records, malformed compatibility, and rate-limit outcomes.
- [x] 1.5 Document gallery-dl 1.32.2 commit `2e88d6ae29780dbed02e4a5172a1aa0a1b1c91b5` as a comparison oracle and add reviewed expected-mapping fixtures without importing or executing gallery-dl in the normal test suite.

## 2. Catalog Schema and Persistence

- [x] 2.1 Add a numbered migration for remote runs, requests, resumable checkpoints, run ancestry, counters/budgets/outcomes, and raw-observation request provenance with constraints and indexes.
- [x] 2.2 Add platform-scoped tags, stable post-tag associations, append-only tag observations, neutral attribution entities/snapshots/names/URLs/tag links, and their provenance constraints.
- [x] 2.3 Extend post and media persistence for title, provider post type, update time, rating, occurrence role, MIME type, and non-negative declared file size while preserving existing rows and partial-update semantics.
- [x] 2.4 Add schema tests for fresh creation, schema-v4 upgrade and backfill, failed-migration rollback, foreign keys, uniqueness, checks, ID preservation, and compatibility with existing import and asset tables.
- [x] 2.5 Extend validated record types and `CatalogWriter` contracts for platform-associated raw observations, remote-run state, tags, attribution entities, richer posts, and richer media occurrences.
- [x] 2.6 Add idempotency and history tests proving raw payload deduplication preserves distinct remote observations, tag spelling/category history survives, attribution cannot become an account implicitly, and later partial metadata does not erase known values.
- [x] 2.7 Extend read-only query/result APIs for remote runs, requests, tags, attribution records, and rich occurrence metadata without exposing raw payloads, credentials, or private configuration by default.

## 3. Remote Synchronization Service

- [x] 3.1 Implement the synchronization facade and persistence collaborator that create auditable runs, capture request attempts/raw responses, and atomically normalize a retained response with counters and checkpoint advancement.
- [x] 3.2 Implement immutable positive request/page/record/time budgets, pre-request enforcement, whole-page record admission, deterministic termination reasons, and child-run resume from only a committed compatible checkpoint.
- [x] 3.3 Implement the shared HTTP request gate with injected transport/clock/sleeper, conservative provider pacing, bounded retries, allowlisted rate-limit metadata, and retry delays capped by remaining budgets.
- [x] 3.4 Implement secret-free canonical request identities and an environment-reference credential resolver; sanitize transport/provider exceptions and exclude token-exchange responses from raw capture.
- [x] 3.5 Add crash/replay tests covering raw capture followed by normalization failure, no checkpoint advancement on failure or oversized pages, committed-page resume, incompatible continuation versions, idempotent replay, and independent repeat runs.
- [x] 3.6 Add security tests using sentinel secrets to verify database bytes, raw payloads, diagnostics, exceptions, logs, request identities, reprs, and structured results never contain credentials.
- [x] 3.7 Add network-isolation tests proving fixture execution makes no unmocked HTTP requests and metadata synchronization never requests media URLs, links assets, or changes managed storage.

## 4. Pixiv Metadata Adapter

- [x] 4.1 Implement isolated Pixiv authentication and metadata transport for stable user detail, artwork detail, bounded user-artwork pages, and Ugoira metadata with injected HTTP dependencies and typed provider outcomes.
- [x] 4.2 Implement Pixiv profile normalization to stable numeric accounts, temporal metadata, avatar/background URLs, counts, account state, and external profile-link observations.
- [x] 4.3 Implement artwork normalization for title/caption/type/times/state, publishing-account author role, original tags/translations, and one stable ordered occurrence per page with versioned variants.
- [x] 4.4 Implement Ugoira normalization that retains archive/frame-delay metadata in order without fetching, extracting, converting, or creating an asset.
- [x] 4.5 Implement bounded user-artwork continuation handling without implicit enumeration from profile or single-artwork fetches.
- [x] 4.6 Add fixture-contract and catalog integration tests for stable IDs, profile history, partial responses, multi-page order, URL updates without duplicate pages, tag translations, Ugoira, restricted/deleted records, authentication failure, resume, raw retention, and zero media requests.

## 5. Danbooru-Family Metadata Adapter

- [x] 5.1 Implement explicit Danbooru and AIBooru instance configurations with independent platform keys/base URLs, compatibility/schema versions, identifying user agents, conservative request policies, and external credential references.
- [x] 5.2 Implement post, artist, and bounded listing transports with Basic or query authentication as configured, selected rate-limit metadata, single-post endpoints, and opaque keyset continuations.
- [x] 5.3 Normalize posts with rating/status/times, categorized tags, primary/sample/preview variants, dimensions/MIME/file size, typed availability, and provider MD5 as declared occurrence evidence only.
- [x] 5.4 Normalize stable uploader accounts with only the uploader role, and normalize booru artist records/aliases/tags/URLs as attribution entities that cannot implicitly become accounts or confirmed creators.
- [x] 5.5 Normalize source URLs and provider Pixiv IDs through typed external-reference evidence without automatic post/account/work confirmation, and persist directional parent/child relations idempotently.
- [x] 5.6 Add Danbooru fixture-contract and integration tests for categorized tags, declared-versus-verified hash separation, uploader/artist separation, artist aliases/URLs, source evidence, relations, deletion, rate limits, and `b<ID>` resume.
- [x] 5.7 Add AIBooru parity tests proving independent platform identity and explicit malformed-response failure when its observed response diverges from the declared compatibility contract.

## 6. CLI, Inspection, and Documentation

- [x] 6.1 Add explicit catalog metadata commands for Pixiv profile/artwork/account-artworks and Danbooru/AIBooru post/artist/listing operations with finite documented defaults and user-supplied budget overrides.
- [x] 6.2 Add stable JSON and human output reporting run ID, provider/instance, operation, counters, checkpoint/resume relationship, typed termination reason, and public diagnostics without secrets or raw payloads.
- [x] 6.3 Add remote-run and normalized metadata inspection commands that operate through the catalog's read-only query path and remain usable without network access or provider credentials.
- [x] 6.4 Document credential environment references, provider limitations, conservative use, budget/resume behavior, metadata-only guarantees, fixture regeneration, and the distinction between booru uploaders, artist attribution, and creator identity.
- [x] 6.5 Add disabled-by-default live smoke tests with explicit opt-in, fixed public identifiers, minimal budgets, external credentials, no media hosts, and stable skip behavior when configuration is absent.

## 7. Compatibility and Evaluation

- [x] 7.1 Run characterization tests proving existing X import/discovery, local source imports, asset adoption/verification, read-only access, and offline commands preserve their public behavior after the migration and writer extensions.
- [x] 7.2 Run the full test suite, Ruff, strict OpenSpec validation, SQLite integrity/foreign-key checks on fresh and upgraded catalogs, and repository diff checks.
- [x] 7.3 Request the required `review-mcp` review for the completed implementation, address actionable findings, and rerun every affected quality gate before handoff.
