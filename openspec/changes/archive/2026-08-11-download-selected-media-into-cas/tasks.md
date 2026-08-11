## 1. Acquisition Persistence

- [x] 1.1 Add a forward-only catalog migration for immutable acquisition plans/items, runs/items, append-only attempts, partial-transfer state, verification comparisons, and quarantine records with validated states, foreign keys, uniqueness constraints, and query indexes.
- [x] 1.2 Add fresh-schema, current-schema upgrade, failed-migration rollback, foreign-key, constraint, ID-preservation, and catalog-doctor tests for the acquisition migration.
- [x] 1.3 Add validated acquisition record types and writer operations for creating plans and runs, advancing item/run state, appending attempts, recording partials/comparisons/quarantine, and idempotently completing results.
- [x] 1.4 Add read-only query APIs for plans, runs, mixed-outcome items, bounded attempt evidence, retry eligibility, and resulting asset references, with stable ordering and path/secret redaction tests.

## 2. Explicit Planning and Selection

- [x] 2.1 Implement finite occurrence and variant selection with stable variant keys, provider-policy lookup, declared-claim capture, material target digests, eligibility reasons, and already-satisfied detection.
- [x] 2.2 Implement network-free, no-layout, no-migration acquisition planning through the existing read-only catalog boundary and prove that planning does not issue HTTP requests or mutate the catalog or managed root.
- [x] 2.3 Implement execution-time target re-resolution and stale-plan rejection for changed URLs, variants, policy versions, source observations, and material declared claims.
- [x] 2.4 Add planning tests for primary and named variants, multi-page Pixiv occurrences, Danbooru original/sample/preview variants, ineligible sources, duplicate selections, and already linked assets.

## 3. Remote Staging and Quarantine Safety

- [x] 3.1 Extend `AssetStorage` with a descriptor-bound remote staging session that creates, writes, flushes, reopens, inspects, finalizes, and safely cleans up catalog-owned partial files without accepting caller-selected paths.
- [x] 3.2 Add validated partial reopening that checks managed-root identity, staging ownership, regular-file type, inode binding, recorded size, request identity, and recomputed prefix hashes before permitting append.
- [x] 3.3 Add bounded descriptor-relative quarantine publication and records for retained integrity evidence without treating quarantine entries as CAS assets or exposing private paths.
- [x] 3.4 Add focused race, symlink, component-substitution, partial-truncation/growth, process-reopen, lock, cleanup-ownership, fsync-ordering, quarantine-budget, and injected-failure tests for the new storage primitives.

## 4. Provider Media Request Policies

- [x] 4.1 Define versioned provider-neutral request-policy and ephemeral request-recipe contracts covering allowed destinations, required headers, credential resolution, redirect validation, response expectations, retry classification, and secret-free durable identities.
- [x] 4.2 Implement central URL and redirect validation that rejects unknown providers, arbitrary hosts, user-info, IP literals, unexpected ports, non-HTTPS or downgrade targets, and every off-policy redirect before it is requested.
- [x] 4.3 Implement the Pixiv media policy with its allowed media hosts, referer/authentication behavior, variant resolution, and redacted identity; cover original pages and Ugoira archives with offline fixtures.
- [x] 4.4 Implement instance-configured Danbooru and AIBooru media policies with explicit trusted CDN hosts, original/sample/preview resolution, provider MD5 association, and offline fixtures.
- [x] 4.5 Add adversarial secret-redaction tests covering bearer tokens, cookies, credential configuration, signed query values, redirects, exceptions, persisted attempts, and structured output.

## 5. Bounded HTTP Transfer and Resume

- [x] 5.1 Implement an injected `httpx` streaming transfer engine with manual redirects, fixed-size chunks, item/run byte accounting, content-length preflight, elapsed deadlines, cancellation checks, bounded retries/backoff, and `Retry-After` handling.
- [x] 5.2 Implement durable attempt transitions and typed outcomes for policy, authentication, authorization, unavailable, rate-limited, retryable provider, timeout, response-size, content, source-changed, interruption, and local-storage failures.
- [x] 5.3 Implement strict partial resume using strong ETag, `Range`, and `If-Range`, accepting append only for matching validators and coherent 206 `Content-Range` responses.
- [x] 5.4 Implement safe restart or quarantine behavior for missing/weak/changed validators, ignored ranges, inconsistent lengths, and changed request identities without ever concatenating incompatible representations.
- [x] 5.5 Add zero-network transport tests for redirect chains, retry budgets, run-budget exhaustion, short/incomplete bodies, oversized chunked responses, interruption, validated resume, every invalid resume response, and deterministic injected time.

## 6. Verification, Publication, and Reconciliation

- [x] 6.1 Feed completed remote staging through existing bounded exact hashing, MIME/dimension/frame inspection, perceptual fingerprinting, and exact-only classification without weakening current adoption limits.
- [x] 6.2 Compare only variant-compatible declared hashes, sizes, MIME types, and dimensions with verified results while preserving both assertion and calculation provenance; quarantine exact-hash mismatches before linking.
- [x] 6.3 Orchestrate managed-root locking, verified CAS publication/reuse, database asset/location/fingerprint/source persistence, and idempotent occurrence-to-asset linking in the publication-first order.
- [x] 6.4 Implement reconciliation for a valid CAS object left after database interruption, and fail closed for corrupt/colliding existing targets without redownloading or overwriting bytes.
- [x] 6.5 Add integration tests for successful Pixiv and Danbooru-family downloads, shared-byte deduplication, exact-only media, provider MD5 match/mismatch, publication interruption, database interruption, repeated execution, and import/staging inputs that cannot bypass verification.

## 7. Run Orchestration and Retry

- [x] 7.1 Implement the acquisition facade with positive immutable limits for items, item/run bytes, attempts, elapsed time, redirects, quarantine bytes, and concurrency, using serial execution initially.
- [x] 7.2 Implement durable recovery of interrupted attempts and deterministic aggregate run states and counters for complete, partial, failed, quarantined, stale, deferred, and budget-exhausted work.
- [x] 7.3 Implement retry runs linked to their predecessor that select retryable failed/interrupted items by default, preserve prior attempts, skip satisfied/successful items, and require explicit inclusion of non-retryable outcomes.
- [x] 7.4 Add lifecycle tests for interruption at every durable boundary, first-budget-wins behavior, retry eligibility, no duplicate completed attempts, no implicit network activity, and stable mixed-outcome summaries.

## 8. CLI, Documentation, and Evaluation

- [x] 8.1 Add distinct `catalog assets` planning, execution, run-list/show, and retry commands with explicit occurrence/variant selection, managed-root and positive budget arguments, stable JSON output, and non-success exit status for incomplete requested work.
- [x] 8.2 Document the acquisition workflow, provider credentials and trusted media-host configuration, budgets, strict resume behavior, quarantine, reconciliation, declared-versus-verified values, and the fact that metadata sync never downloads media.
- [x] 8.3 Document gallery-dl as a behavioral reference and possible future external bridge only; add a boundary test demonstrating that an externally produced file remains untrusted until normal verification and CAS publication succeeds.
- [x] 8.4 Add opt-in, credential-external, hard-bounded live smoke tests for one Pixiv image and one Danbooru-family image while keeping the default suite fully offline.
- [x] 8.5 Run focused migration/storage/policy/transfer/service/CLI tests, the full offline test suite, Ruff, `git diff --check`, and strict OpenSpec validation; request review-mcp, address actionable findings, and rerun affected gates.
