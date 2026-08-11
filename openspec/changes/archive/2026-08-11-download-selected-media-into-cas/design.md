## Context

See `proposal.md` for motivation and `specs/remote-media-acquisition/spec.md` for the behavioral contract. The catalog currently has two deliberately separate paths:

- `MetadataSyncService` obtains bounded provider metadata and persists media occurrences and variants without requesting media bytes.
- `AssetStorage` and the adoption service stage local files, calculate exact and perceptual fingerprints, publish immutable SHA-256-addressed bytes, and link verified assets to occurrences.

The missing layer is an explicit remote acquisition orchestrator. It must reuse the second path's safety properties while adding HTTP-specific request policy, partial-transfer validation, durable attempts, and run-level budgets. The existing `httpx` dependency is sufficient for transport. gallery-dl's HTTP downloader provides useful behavioral reference material, but it is coupled to gallery-dl extractors, jobs, global configuration, path formatting, and GPLv2 implementation code; it is not a stable storage API for this catalog.

## Goals / Non-Goals

**Goals:**

- Create one provider-neutral acquisition lifecycle for selected occurrence variants.
- Make planning read-only and network-free, and make all network activity explicit.
- Preserve durable operational history without persisting credentials or sensitive rendered URLs.
- Resume only when partial bytes can be proven to belong to the same remote representation.
- Feed complete remote bytes through the existing verification, CAS, and catalog-linking invariants.
- Recover safely across failures before transfer, during transfer, after CAS publication, and during database persistence.

**Non-Goals:**

- Automatic downloads during metadata synchronization or discovery.
- Account-wide crawling, search expansion, or automatic original/best-variant selection.
- Similarity thresholds, visual relationship classification, work grouping, or creator inference.
- A general download manager, browser automation layer, video transcoder, or gallery-dl library fork.
- Deleting or lifecycle-managing quarantined evidence beyond bounded creation and inspection.

## Decisions

### 1. Add an acquisition facade beside metadata sync and local adoption

Add a public acquisition service responsible for selection, immutable plans, budgets, run and attempt state, transfer orchestration, reconciliation, and structured results. It delegates four narrow responsibilities:

```text
catalog occurrence + chosen variant
                │
                ▼
      provider request policy
                │ ephemeral request recipe
                ▼
       bounded HTTP transfer
                │ retained staging handle
                ▼
    inspect / verify / quarantine
                │ verified staged asset
                ▼
      existing CAS publication
                │
                ▼
 asset + fingerprints + provenance + occurrence link
```

Metadata adapters remain metadata-only and do not receive storage handles. `AssetStorage` remains the sole publisher of managed bytes. The acquisition facade is the only component allowed to coordinate both network transfer and catalog asset persistence.

Alternatives considered:

- Extend `MetadataSyncService` to download URLs: rejected because fetching metadata and authorizing storage have different budgets, retry semantics, and user intent.
- Treat remote downloads as local adoption: rejected because a source path cannot represent redirects, credentials, validators, response status, or partial transfers.
- Let provider adapters publish assets: rejected because it duplicates CAS and persistence invariants across providers.

### 2. Persist immutable plans separately from execution attempts

Add acquisition plans, plan items, runs, run items, attempts, and partial-transfer records (exact table names may follow existing schema conventions). A plan item snapshots:

- occurrence ID and stable variant key;
- a digest of the material occurrence/variant fields used for planning;
- provider and versioned request-policy identity;
- source observation/provenance IDs when available;
- known declared size, MIME, dimensions, and exact-hash assertions;
- eligibility or exclusion reason.

It does not copy credentials or a sensitive rendered request URL. Execution re-resolves the selected occurrence and compares the material digest before requesting it. Refreshing a plan is explicit and creates a new snapshot rather than rewriting historical authorization.

A run references one plan and records immutable budgets, mutable counters, status, timestamps, and an optional predecessor for retries. Run items record their own terminal or retryable outcome. Every HTTP exchange is a separate attempt so retries do not erase evidence.

Planning opens the catalog read-only and performs no filesystem layout creation or HTTP request. Positive limits are required for execution: maximum selected items, item bytes, total bytes, attempts per item, elapsed seconds, redirects, and concurrency. The first implementation uses concurrency one while persisting the limit in a forward-compatible form; this reduces managed-root locking and budget races without defining a permanently serial contract.

### 3. Resolve provider-specific request recipes only at attempt time

Define a `MediaRequestPolicy` contract keyed by provider/instance and policy version. It validates the selected variant and produces an ephemeral request recipe containing method, rendered URL, non-secret required headers, a credential resolver reference, allowed schemes/hosts/ports, allowed redirect hosts, retry categories, and response expectations.

Built-in policies cover Pixiv and the configured Danbooru-family instances introduced by the previous change. Pixiv policy supplies its required referer/auth behavior and restricts requests to known Pixiv media hosts. Danbooru-family policy derives explicit media/CDN hosts from trusted instance configuration rather than accepting arbitrary hosts from occurrence data. Every redirect is handled manually and revalidated before the next request. IP-literal, user-info, downgrade-to-HTTP, unexpected-port, and off-policy destinations fail closed.

The persisted request identity contains the policy key/version, operation, provider, occurrence/variant IDs, and a digest of allowlisted non-secret request material. It never contains credential values, cookie contents, authorization headers, or sensitive query parameters. Exceptions and response diagnostics pass through the existing bounded/redacted output boundary.

Generic arbitrary-URL downloading was rejected because catalog metadata is not a sufficient SSRF authorization boundary. Users can add a provider policy for another trusted instance later.

### 4. Own a small HTTP transfer engine instead of embedding gallery-dl

Use an injected `httpx` client/transport, clock, and sleeper behind a catalog-owned transfer contract. The engine disables automatic redirects, streams fixed-size chunks, checks cancellation/deadlines between chunks, and charges received bytes against both item and run budgets. Retryable HTTP statuses, transport errors, `Retry-After`, and backoff all pass through the shared attempt and elapsed-time gates.

gallery-dl remains a reference for provider quirks, partial-file behavior, throttling, and fixtures. Its downloader is not imported because it depends on gallery-dl job/extractor/path state and would write outside the catalog's staging lifecycle. Copying implementation code is also avoided. A future subprocess bridge may emit metadata or a completed file into an isolated source directory; that file then enters the ordinary adoption/acquisition verification boundary as untrusted input.

Alternatives considered:

- Invoke gallery-dl for every transfer: rejected because it obscures per-attempt budgets and redirect policy, owns destination paths, and requires a second import/reconciliation lifecycle.
- Import `gallery_dl.downloader.http`: rejected because it has no standalone stable interface and is coupled to gallery-dl internals.
- Add a second HTTP dependency: rejected because `httpx` already provides streaming, injected test transports, timeout control, and explicit redirect handling.

### 5. Extend staging with a remote-stream writer, not a synthetic source file

Extend `AssetStorage` with a bounded remote staging session that creates and retains descriptor-bound staging state under the managed root. The transfer layer may append only through this session; it cannot choose filesystem paths or publish targets. Finalization rewinds and derives hashes/inspection evidence from the staged bytes, then returns the same verified staged-asset shape used by CAS publication.

The extension preserves existing no-follow traversal, managed-root identity, exclusive lock, owned-cleanup, inode binding, atomic publication, target verification, and fsync ordering. It does not route remote data through a fake source root because doing so would weaken provenance and path-containment semantics.

Partial records store an opaque owned staging name, byte count, response validator, source/request identity digest, and timestamps. They do not store open descriptors across processes. On resume, the service reopens the owned staging entry descriptor-relative, verifies its type and recorded size, and recalculates exact hashes over the prefix before appending. Rehashing is intentionally preferred over persisting non-portable internal hash states.

### 6. Resume only with a strong validator and a valid content range

A partial response is resumable only when the original response supplied a strong ETag retained in redacted operational state. A later attempt sends `Range: bytes=<recorded-size>-` and `If-Range: <etag>`. Append occurs only after validating status 206, the exact starting offset, a coherent total length when supplied, and the same strong validator.

If the validator is absent or weak, changes, the server returns 200, or `Content-Range` is inconsistent, the existing partial is never appended. It is safely discarded or quarantined according to the failure category and the response restarts from byte zero within the same budgets. Last-Modified alone is not treated as proof that byte representations match.

This is intentionally stricter than gallery-dl's size-based Range resume. It may redownload some bytes, but it cannot silently concatenate different remote representations.

### 7. Separate source assertions, verified facts, and quarantine evidence

Provider-declared hash/size/MIME/dimension values remain occurrence assertions with their original provenance. Acquisition calculates new SHA-256 and MD5 fingerprints and detected media properties from complete staged bytes using the existing inspection limits and algorithm/version records. Comparison creates an acquisition verification result; it never updates a provider assertion into a locally verified fact.

Compatible exact-hash disagreement is a terminal integrity mismatch. The bytes are not linked as a successful acquisition. When evidence retention is enabled, the owned staging entry is moved descriptor-relative into the managed root's existing quarantine area under an opaque generated name and recorded with reason, size, calculated hashes, plan item, and attempt. Quarantine has a per-run byte budget and is never considered a CAS asset. Oversized or incomplete responses may retain metadata-only evidence rather than bytes.

Unsupported but permitted formats can publish as exact-only assets when signature/MIME policy and byte verification succeed. Decode failures for formats expected to be safely inspectable remain inspection failures rather than silently becoming successful images.

### 8. Publish first, then persist idempotently, with reconciliation

The successful order is:

1. complete and verify staging;
2. publish or verify the deterministic CAS object under the managed-root lock;
3. in one bounded database transaction, upsert the asset, managed location, calculated fingerprints, occurrence source/provenance, acquisition result, and occurrence-to-asset link;
4. mark the run item complete.

CAS publication cannot participate in a SQLite transaction, so a crash between steps 2 and 3 can leave an unreferenced but valid CAS object. Retry derives the same SHA-256 path, verifies the existing bytes, and completes database persistence without another media request. A database record is never committed before its CAS object is durable.

Stable uniqueness keys cover plan snapshots, run item membership, individual attempt numbers, SHA-256 assets, managed locations, calculated fingerprints, and occurrence/asset associations. Historical attempts are append-only; only aggregate run/item state advances.

### 9. Expose acquisition beneath the existing assets CLI

Extend `catalog assets` with a distinct remote-acquisition command family, for example:

```text
catalog assets download-plan ...
catalog assets download ...
catalog assets download-runs ...
catalog assets download-show ...
catalog assets download-retry ...
```

Selection accepts explicit occurrence identifiers and optional variant keys, plus bounded query filters that resolve to a finite displayed plan. Execution requires a catalog and managed root plus positive limits. Structured output uses stable public IDs, deterministic counts, policy/version identities, hashes when safe, and redacted source labels; it omits absolute staging/quarantine paths and rendered authenticated URLs.

Read-only list/show/plan operations use the existing no-migration read-only database boundary. Exit status is non-success for partial, failed, quarantined, stale, or budget-exhausted requested work, consistent with asset adoption and verification commands.

## Risks / Trade-offs

- [Provider media hosts and required headers change] → Version policies independently of metadata schemas, reject unknown destinations, and cover known provider flows with offline transport fixtures plus opt-in bounded smoke tests.
- [Strict validator rules cause more restarts] → Prefer correctness over bandwidth; retain explicit restart reasons and add provider-specific safe validators only with evidence.
- [Partials and quarantine consume disk] → Enforce item/run/quarantine byte budgets, expose them in inspection output, and leave deletion to a later explicit lifecycle change.
- [A process crash leaves a valid unreferenced CAS object] → Reconcile deterministically by verified SHA-256 before any redownload; managed-storage verification continues to report true orphans.
- [Signed URLs expire between planning and execution] → Persist provider policy and stable variant identity, resolve ephemeral recipes at attempt time, and classify refreshable authorization/source-expiry failures separately.
- [Provider-declared hashes describe another variant] → Compare only assertions explicitly associated with the selected variant and preserve unmatched assertions without drawing a mismatch conclusion.
- [Single-worker execution is slower] → Persist concurrency limits and keep orchestration separable, but defer parallel root-safe scheduling until serial correctness is established.

## Migration Plan

1. Add forward-only schema migration(s) for acquisition plans/items, runs/items, attempts, partial state, verification comparisons, and quarantine records with constraints, foreign keys, indexes, and upgrade tests from the current schema.
2. Add writer/query records and read-only inspection APIs without changing existing metadata, adoption, or asset behavior.
3. Add remote staging and partial-reopen primitives behind focused descriptor-relative, substitution, interruption, and durability tests.
4. Add provider request policies and the injected bounded transfer engine with zero-network fixtures.
5. Add orchestration and CLI commands, then enable Pixiv and Danbooru-family policies.
6. Run migration, full offline suite, Ruff, strict OpenSpec validation, and review-mcp before live smoke testing.

Rollback before acquisition is used can restore a backed-up pre-migration catalog and remove newly created managed-root acquisition staging. After successful acquisition, rollback must first preserve the catalog backup and CAS bytes; schema downgrade is not performed in place. Existing commands continue to operate against the migrated catalog if the acquisition command family is not invoked.
