## 1. Provider Contracts and Fixtures

- [x] 1.1 Verify current Danbooru and AIBooru source-URL, external-ID, MD5, exact artist-name, alias, and bounded text-query behavior against primary provider documentation and minimal redacted responses; record unsupported instance capabilities instead of assuming parity.
- [x] 1.2 Add synthetic/redacted fixtures for source hits and misses, X URL aliases, MD5 hits, multiple artist-name results, artist aliases/external URLs, unrelated uploaders, pagination, unavailable records, malformed payloads, authentication failures, and 429 outcomes.
- [x] 1.3 Add closed lookup-strategy, capability, private query-material, plan-item, normalized lookup-result, and versioned continuation contracts with validation and stable serialization tests.

## 2. Durable Lookup Persistence

- [x] 2.1 Add a numbered additive migration for lookup runs, requests, checkpoints, and results with exactly-one-seed constraints, immutable positive limits, closed strategies/outcomes/result kinds, predecessor links, raw-observation provenance, stable result digests, foreign keys, and query indexes.
- [x] 2.2 Add validated record and writer contracts for beginning/finishing lookup runs, retaining attempts, committing page results/checkpoints, and associating normalized posts, attribution entities, platform references, and match evidence idempotently.
- [x] 2.3 Add migration tests for fresh creation, upgrade from the current schema with ID/data preservation, rollback on failure, constraint enforcement, foreign-key integrity, future-version rejection, and unchanged metadata-sync behavior.
- [x] 2.4 Add read-only redacted lookup run/result queries with bounded pagination, stable ordering, typed references, truncation indicators, and no raw query material, payload, URL, header, credential, or private-path fields.

## 3. Shared Bounded Remote Execution

- [x] 3.1 Add characterization tests for existing metadata synchronization covering response-first retention, retries, budgets, whole-page admission, checkpoint timing, resume compatibility, typed failures, result JSON, and zero media requests.
- [x] 3.2 Extract reusable request-gate, raw-retention, budget, and page-commit orchestration behind internal contracts while preserving `MetadataSyncService`, CLI, database, and adapter behavior exactly.
- [x] 3.3 Implement lookup-specific run execution and compatible successor-run resume using the shared substrate, with durable paused/interrupted/rate-limited outcomes and no continuation advancement for an uncommitted page.
- [x] 3.4 Add kill/retry/idempotency tests proving committed pages are neither skipped nor duplicated and incompatible adapter, schema, strategy, seed revision, or private query material cannot resume.

## 4. Danbooru-Family Lookup Adapters

- [x] 4.1 Add independent Danbooru/AIBooru capability declarations and fail-closed planning for unsupported strategies without issuing a request.
- [x] 4.2 Implement fixed-endpoint post lookup by canonical source URL aliases, supported embedded external IDs, and validated MD5, with opaque request identities and bounded provider pagination.
- [x] 4.3 Implement supported exact-name, alias, and bounded artist-text lookup while retaining provider artist IDs, names, aliases, deprecation/replacement state, external URLs, result order, and uploader separation.
- [x] 4.4 Normalize lookup pages through existing post/attribution persistence without converting declared hashes to verified facts or attribution entities to accounts; prove fixture parity and request-policy enforcement with injected transports.
- [x] 4.5 Add optional live smoke tests disabled by default, limited to one request and a small response envelope, that record no credentials, query URLs, personal fixture data, or media bytes.

## 5. Planning and Evidence Interpretation

- [x] 5.1 Implement read-only, network-free plan generation from stable account/post seeds, explicitly selected weak search terms, per-instance capabilities, immutable limits, bounded X source aliases, declared/verified hash provenance, aggregate request bounds, and material digests.
- [x] 5.2 Reject missing/ambiguous seeds, unverified hash claims, unsupported strategies, arbitrary endpoints/parameters, non-positive or excessive limits, and stale plan material with bounded redacted errors.
- [x] 5.3 Interpret canonical source matches as directionally correct `sourced_from` evidence and verified MD5 matches as `same_work` plus `exact_bytes`, while retaining declared-only hash evidence at its weaker classification.
- [x] 5.4 Route provider artist URLs through existing typed URL recognition and candidate generation only when they expose stable account identifiers; retain names, aliases, tags, and uploaders as weak lookup results otherwise.
- [x] 5.5 Add regression tests proving multiple strategies strengthen one stable candidate, repeated results are idempotent, evidence generation advances without changing review state, rejected/confirmed decisions survive, and no account/identity is inferred from hashes, names, artist tags, or uploaders.
- [x] 5.6 Add synthetic end-to-end cases based on the existing X/Pixiv/booru examples for direct source resolution, exact-hash resolution, artist-record-to-Pixiv references, ambiguous names, no-result outcomes, and Twitter-recompressed hash misses treated as inconclusive.

## 6. Public Service and CLI

- [x] 6.1 Add a public `CandidateLookupService` facade over planner, executor, interpreter, resume, and query collaborators without changing offline `DiscoveryService` or ordinary `MetadataSyncService` entry points.
- [x] 6.2 Add `catalog lookup plan`, `run`, `resume`, `runs`, and `show` commands with explicit provider/strategy/seed selection, positive capped limits, stable JSON, bounded human output, typed exit status, and existing match/attribution/result references.
- [x] 6.3 Add adversarial tests with network disabled for plan/query commands and injected network for execution, proving no implicit traversal, account enumeration, media request, download, liked/bookmarked event, similarity computation, or automatic review decision occurs.
- [x] 6.4 Add output-policy tests proving credentials, cookies, headers, raw payloads, private paths, source query material, signed values, rendered request URLs, and response URLs never appear in plans, results, diagnostics, logs, exceptions, or structured output.
- [x] 6.5 Document capability inspection, strong versus weak lookup evidence, dry-run and finite execution, resume behavior, result review, explicit metadata-sync handoff, and the boundaries before expansion, acquisition, and similarity work.

## 7. Verification and Review

- [x] 7.1 Run focused adapter, persistence, discovery/review, remote-sync, lookup, and CLI tests plus the full offline suite, Ruff, `git diff --check`, and strict OpenSpec validation.
- [x] 7.2 Request review-mcp for the complete implementation, address actionable findings, and rerun affected gates before sync, archive, and commit.
