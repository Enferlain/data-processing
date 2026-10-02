# Changelog

<!-- markdownlint-disable MD024 -->

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Rules:
- Use proper sub titles "Added", "Changed", "Removed" and "Fixed"
- Keep proper track of days for where entries should go
- Be concise but mention all changes without necessarily detailing each one

## [2026-10-02]

### Added

- **The Gelbooru DAPI JSON adapter is implemented** — `GelbooruAdapter` renders explicit authenticated
  requests for single-post fetch (`id=`), tag metadata (`name=`), and bounded post listings (`pid`/`limit`),
  normalizes fixture-proven response shapes (list, dict, bare-array, missing-key empty, three error
  envelope forms) into provider-neutral `NormalizedItem` pages covering posts, accounts, uploader
  participants, unknown-category tags, media occurrences with original/sample/preview variants,
  and source references; `_gelbooru_timestamp` handles both ctime-like and `YYYY-MM-DD HH:MM:SS`
  timestamp formats observed in live captures.
- **Gelbooru DAPI adapter tests verify request shapes, typed outcomes, and normalization** — 27
  injected-transport tests pin exact rendered request parameters, the 100-entry page ceiling, status
  code-to-outcome mapping (401/403/404/429/5xx/error-envelope/malformed), response-first raw
  retention, continuation validation, listing continuation with pid increment, idempotent
  normalization against fixture data, zero media-host requests, and all three DAPI response shapes.
- **The Gelbooru anonymous HTML adapter is implemented** — `GelbooruHtmlAdapter` performs exactly one
  unauthenticated GET to the canonical post page with no login, cookies, or media requests;
  fail-closed parsing requires `<title>` and `<img id="image">` markers, detects challenge pages
  via missing tag-list and statistics, and normalizes fixture-proven fields (title, source, uploader,
  rating, score, declared hash, dimensions, tag-category classes, original/sample/preview references).
- **Gelbooru HTML adapter tests verify bounded parsing and typed outcomes** — 22 tests cover
  single-request behavior, canonical request identity, marker extraction, category preservation,
  no secondary requests, no media access, no credentials or cookies, and fail-closed handling of
  missing title, missing image, challenge pages, 404, 403, empty payloads, and non-UTF8 responses.
- **Gelbooru metadata flows through the shared remote-sync stack** — both adapters now expose the
  provider pacing floor for the bounded executor and emit score facts in the mapping form the page
  writer persists; HTML tag categories map onto the neutral vocabulary (`metadata` → `meta`), and
  a six-test synchronization suite drives real catalog persistence over injected transports to
  prove raw-first retention before normalization, atomic page commits with checkpoint/resume for
  `pid` listings, DAPI/HTML observations coexisting as separate transport-identified raw records
  under one reconciled post identity, challenge denial without normalized writes, and rollback
  that keeps the retained raw attempt when a page commit fails midway.
- **Gelbooru tag-category and attribution policy is proven in persistence** — four more
  synchronization tests pin uncategorized DAPI tags keeping their native spelling under neutral
  `unknown`, HTML categories carrying only the fixture-proven neutral values, the uploader
  participant staying distinct from artist/creator attribution (no attribution entities are
  invented), and metadata runs writing zero liked/bookmarked activity observations; the shared
  page writer's fallback for a post tag without a category changed from `general` to `unknown` so
  a provider that stays silent is never recorded as claiming the tag is general.
- **The Gelbooru current-projection and metadata-only policies are pinned** — a later HTML
  observation never erases DAPI-proven facts (original URL, declared MD5, dimensions, post
  status all survive omission), a later DAPI observation fills the gaps an HTML-only view
  lacked, a disagreeing rating resolves to the newer observation while both raw payloads keep
  the audit trail, and returned media URLs stay browseable metadata-only variants with declared
  MD5 as a provider assertion and zero asset or acquisition rows after synchronization.

### Changed

- **Gelbooru schema audit timestamp corrected** — live captures use ctime-like format with timezone
  offset (`Wed Jul 30 10:16:34 -0500 2025`); the adapter normalizes to UTC ISO, and schema audit
  and adapter test expectations now match the actual normalized timestamps.

### Fixed

- **Gelbooru adapters harden typed failures after a three-angle review** — DAPI post records with
  missing or unparseable `created_at` now raise `malformed_response` instead of crashing with
  `KeyError`/`ValueError`; malformed listing continuation payloads are rejected with a clear
  `ValueError` before network access; oversized response bodies raise the new
  `response_too_large` outcome (matching the pinned fixture contract) in both DAPI and HTML
  transports; httpx transport exceptions are re-raised as `transient_provider` with credential
  values scrubbed from the message; the HTML challenge check now runs before the identity-marker
  checks so well-formed challenge pages yield `authorization_denied` instead of
  `malformed_response` while truncated markup without a title still fails as malformed; and HTML
  post items carry an explicit null `status` for shape consistency with DAPI observations. Nine
  new injected-transport tests pin these behaviors. Two review findings were verified as false
  alarms (the Source regex is bounded by the opening tag; the malformed fixture is valid JSON),
  and one — sample-versus-original dimensions — was already handled by preferring the `Size:`
  statistic.

## [2026-10-01]

### Added

- **The Gelbooru schema audit proves the neutral schema needs no migration** — a fixture-driven
  round-trip suite persists every proven Gelbooru fact (platform seed, posts with ratings and
  declared hashes, uploader participants, unknown-category tags with native numeric codes,
  transport-identified raw observations and remote runs) while exercising foreign-key,
  origin-immutability and vocabulary triggers, idempotent re-upserts with stable IDs, rollback
  cleanliness, and doctor checks; tag ambiguity stays recoverable through retained raw payloads.
- **The reviewed Gelbooru fixture contract is documented** — a provider contract record now covers
  observed request and response shapes, post/tag field types, envelope variants, page-number
  pagination semantics, tag-category evidence, media variants, status-to-outcome mapping, pacing
  and redaction decisions, and every unresolved provider assumption, split by provenance
  (observed, reference-corroborated, synthetic, deferred).
- **Gelbooru error and tag fixtures pin typed outcomes** — observed shapes (numeric-type tag
  records, count-zero not-found envelopes, anonymous 401 with empty body) plus
  documentation-derived synthetic 403/5xx/oversized/malformed envelopes cover every typed DAPI
  and HTML failure mode except rate limiting, which stays deferred until actually observed; the
  rate-limit gap is recorded in the fixture manifest.
- **Reviewed Gelbooru fixtures pin the documented post examples** — live credentialed DAPI and
  anonymous HTML captures of the five planned posts (including the text/clean variation pair and
  the distinct third image) are committed as redacted contract fixtures with derived expected
  summaries, stripped inline scripts and session token values, marker-region HTML reduction, and
  tests asserting the variation relationships from the example plan.
- **Gelbooru credential material is scrubbed by a shared redaction boundary** — DAPI credentials
  now join query parameters only through a single final-boundary helper, and a reusable scrubber
  removes credential values and credential-bearing URLs from transport exceptions and any durable
  record, diagnostic, or output surface, pinned by sentinel-based tests.
- **Focused compatibility tests pin catalog writer idempotency and errors** — repeat upserts across
  account, post, media, observation, link-observation, and asset writes now assert the
  inserted/existing/updated outcomes with stable row identifiers, and the exact texts of platform,
  discovery, observation, raw-observation, and remote-run validation errors are asserted through
  the facade.

### Changed

- **The roadmap tracks the active Gelbooru milestone** — the completed e621 verification handoff
  milestone is retired with e621 capabilities marked complete, and the current milestone now names
  the bounded Gelbooru metadata adapter together with its explicit live-capture authorization
  gate.
- **Discovery and core-catalog writes moved behind internal persistence components** — the three
  discovery run/link-observation methods and the seven account, post, participant, observation,
  relation, media-occurrence, and asset-link methods now live in
  `media_catalog.persistence.discovery.DiscoveryWrites` and `...catalog.CatalogWrites`, with
  `CatalogWriter` delegating identically on the caller's shared transaction.
- **Tag, attribution, and external-reference writes moved behind an internal persistence
  component** — tag, tag-alias, post metadata/pool/flag, attribution, and external reference/link
  write methods now live in `media_catalog.persistence.metadata.MetadataWrites` together with the
  attribution-name and reference-URL helpers only they use, delegated identically by
  `CatalogWriter`.
- **Remote synchronization writes moved behind an internal persistence component** — raw
  observation storage and the remote run, request, and checkpoint write methods now live in
  `media_catalog.persistence.remote.RemoteWrites`, delegated identically by `CatalogWriter` with
  transport-identity checks preserved.
- **Candidate-lookup and library-expansion writes moved behind internal persistence components** —
  the five lookup run/request/checkpoint/result methods and four library plan/probe/execution/post
  methods now live in `media_catalog.persistence.lookup.LookupWrites` and
  `...library.LibraryWrites`, with identical public signatures delegated by `CatalogWriter`; the
  platform-identity lookup became a shared support helper the facade and components both use.
- **Acquisition writes moved behind an internal persistence component** — the nine acquisition
  plan, run, run-item, attempt, partial, verification, and quarantine write methods now live in
  `media_catalog.persistence.acquisition.AcquisitionWrites` with identical public signatures
  delegated by `CatalogWriter` on the caller's shared transaction.
- **Managed-storage and adoption writes moved behind an internal persistence component** — the
  eight root, asset-location, occurrence-source, fingerprint, and adoption write methods now live
  in `media_catalog.persistence.storage.StorageWrites`, with `CatalogWriter` keeping identical
  public signatures as explicit delegations on the caller's shared transaction; the root-upsert
  compatibility alias is preserved.

## [2026-09-30]

### Added

- **Catalog persistence gains an internal shared-support package** — `media_catalog.persistence`
  now provides the connection, timestamp, inserted-id, and write-result helpers that extracted
  writer components will share; `writer.py` imports them while keeping its public surface
  unchanged, and a guard test forbids any component from committing, executing scripts, or
  opening its own connection.

### Changed

- **Catalog record types are organized into domain modules behind the existing import surface** —
  `media_catalog.records` is now a package with discovery, core catalog, remote-sync, metadata,
  storage/adoption, acquisition, candidate-lookup, and library-expansion families re-exported
  compatibly, so existing imports, constructors, validation, and public names are unchanged.
- **The persistence compatibility suite pins the record surface more completely** — characterization
  coverage now also locks record fields and defaults, frozen/slots behavior, annotation resolution,
  per-family validation, and defining module paths, alongside the existing constructor, name, and
  writer-signature digests and the cross-domain rollback test.
- **Agent instruction files corrected** — quality-gate examples in CLAUDE.md and AGENTS.md now
  reference the `media_catalog/records` package instead of the removed single-module path.

## [2026-08-13]

### Added

- **e621 metadata can be synchronized through the catalog** — added a native adapter for bounded
  post, artist, tag, alias, and artist-tag listing requests with descriptive identification,
  optional external Basic-auth credentials, conservative pacing, typed failures, raw-response
  provenance, and resumable ID-keyset pagination without requesting media bytes.
- **e621 provider facts have neutral queryable persistence** — added versioned storage for native
  tag identities and categories, aliases, attribution details, post scores and counts, flags, and
  pool observations while preserving uploader roles, artist attribution, and locally verified
  asset facts as distinct concepts.
- **The metadata CLI supports explicit e621 workflows** — added post, artist, tag, alias, and
  bounded listing commands with finite budgets, stable human and JSON output, checkpoint resume,
  credential privacy, and no implicit media acquisition.
- **e621 evidence can feed bounded lookup and library expansion** — added source-URL, external-ID,
  declared/verified-MD5, exact-name, and approved-alias strategies; stable artist-tag expansion
  with retained-count estimates, opaque `b<ID>` resume, target-scoped browsing, and no fuzzy search
  or automatic identity/authorship conclusions.
- **Selected e621 variants can enter verified acquisition** — added explicit original/sample/preview
  handoff from browse selectors, a bounded `static1`–`static9` host and redirect policy, original-only
  claim comparison, derivative claim separation, quarantine, and CAS reuse without metadata-triggered
  downloads.
- **The catalog guide documents e621 operations and boundaries** — added external credential and
  pacing guidance, dynamic category and alias provenance, privacy/troubleshooting notes, and the
  disabled-by-default live-smoke limitation; Gelbooru and cross-database alias mapping remain future
  work.

### Changed

- **Remote synchronization admits continuation pages before requesting them** — request, page,
  record, and time boundaries now stop unadmitted work before the next provider call, including
  tag and alias pages, while retaining committed checkpoints for safe restart.

## [2026-08-12]

### Added

- **Reviewed or explicitly selected artists can seed bounded library expansion** — added offline
  target resolution, ambiguity handling, Pixiv count probing, Pixiv and Danbooru-family metadata
  enumeration, durable resume lineage, and explicit expansion-to-post provenance without inferring
  identity from handles, names, tags, aliases, or uploaders.
- **Expansion results feed the existing media and acquisition workflow** — added redacted
  list/show inspection, incomplete-detail reporting, target-scoped occurrence browsing, and stable
  variant selectors while keeping metadata enumeration separate from detail hydration and media
  download.
- **The repository now has an evolving project roadmap** — documented the overall goal, working
  pipeline, completed capabilities, current state, next artist-library milestone, future provider
  and operations work, and later supervised similarity research without duplicating Beads tasks or
  the detailed architecture plan.
- **The catalog can perform bounded cross-platform candidate lookups** — added explicit plan, run, resume, list, and show workflows for provenance-rich Danbooru and AIBooru source-URL, platform-ID, hash, artist-name, and alias searches without treating results as identity or authorship proof.
- **Candidate lookups are durable, finite, and review-oriented** — added immutable limits, sanitized request attempts, retained raw observations, checkpoints, typed provider outcomes, result associations, and evidence integration with the existing manual match-review ledger.

### Changed

- **Python quality tooling now has a blocking type-check gate** — added ty as a development
  dependency with Python 3.13 and vendored-code boundaries, resolved the first-party diagnostic
  baseline, expanded Ruff with explicit formatting, comprehension, and absolute-import policy, and
  documented the applicable test, lint, format, and type-check commands for agents.
- **Managed asset code now has a cohesive package layout** — moved content-addressed storage mechanics, local-file adoption, integrity verification, and read-only inspection into `media_catalog.storage` while keeping remote downloads under the separate acquisition boundary.
- **Remote page execution now has a reusable bounded loop** — metadata synchronization and candidate lookup share request, retention, normalization, commit, continuation, and budget semantics without coupling provider adapters to catalog persistence.

## [2026-08-11]

### Added

- **Selected remote media can be acquired into verified managed storage** — added explicit planning and execution, provider-aware request policy, resumable bounded transfers, exact hashing, inspection, quarantine, CAS publication, occurrence linking, and durable run and attempt history.
- **Catalog media occurrences can be browsed without direct SQL** — added bounded read-only list and detail queries with platform, author, post, availability, and asset-link filters plus stable occurrence and variant selections for download planning.

### Changed

- **Declared provider metadata remains distinct from locally verified facts** — acquisition preserves both claims and their provenance, and media browsing reports eligibility and linked assets without exposing remote URLs, credentials, raw payloads, or private paths.

## [2026-08-10]

### Added

- **Existing local media can be adopted into a content-addressed store** — added safe offline planning and execution, descriptor-relative path handling, SHA-256 and MD5 verification, raster inspection, versioned perceptual hashes, atomic publication, exact deduplication, reconciliation, and durable per-file outcomes.
- **Pixiv and Danbooru-family metadata adapters provide bounded synchronization** — added Pixiv profile, artwork, listing, multi-page, tag, and Ugoira normalization together with Danbooru and AIBooru post, artist, uploader, tag, relation, source, hash, and pagination metadata.
- **Remote metadata runs preserve auditability without downloading images** — added strict request, page, post, and time budgets; resumable checkpoints; raw response provenance; typed failures; redacted fixtures; and disabled-by-default live smoke tests.

### Changed

- **Legacy X media paths are occurrence-level provenance rather than managed storage** — imported paths remain non-owning source references until their bytes pass the catalog-owned adoption and verification workflow.

## [2026-08-09]

### Added

- **Offline cross-platform discovery turns retained links into reviewable evidence** — added extraction and canonicalization for profile and post URLs, typed platform references, unresolved-link retention, account and post candidates, deterministic evidence scores, and append-only review history.
- **Confirmed matches have explicit conservative semantics** — added reversible identity membership and post relations while keeping account identity, post equivalence, authorship, work grouping, and image variation as separate claims.

### Changed

- **Discovery responsibilities are split behind the stable service facade** — scanning, candidate generation, queries, review, identity rebuilding, and manual post matching live in focused collaborators without changing CLI or result contracts.

### Fixed

- **URL aliases no longer replace semantic platform-reference associations** — normalized links and references use many-to-many persistence, identifier kinds distinguish stable IDs from handles, slugs, hashes, and opaque values, and mutable X handles cannot materialize identities by themselves.

## [2026-08-05]

### Added

- **A platform-neutral media catalog now complements the X-specific tool** — added a migration-managed SQLite model for platforms, accounts and snapshots, posts, observations, media occurrences, assets, raw records, and import provenance together with initialization, integrity, statistics, and search commands.
- **Existing X likes and xarchive bookmarks can be imported idempotently** — added immutable-source importers that preserve likes and bookmarks as distinct observations, retain unknown provider data, reconcile overlapping exports, and report inserted, updated, existing, skipped, and failed counts.
- **The customized xarchive utility is maintained in-tree** — incorporated the locally extended bookmark parser as repository-owned code for stable bookmark JSON production and integration.

## [2026-08-04]

### Added

- **Each repository tool has a dedicated usage guide** — added the documentation index and a detailed `x-likes` guide covering setup, archive import, enrichment, optional media downloads, hashing, output, and operational caveats.

## [2026-08-03]

### Changed

- **X enrichment retains more accurate saved account and post information** — expanded provider normalization and database updates while preserving unavailable records and improving repeated enrichment behavior.

## [2026-08-02]

### Added

- **The first local-first tool imports and enriches X likes** — added archive parsing, SQLite persistence, provider enrichment, optional image downloading, MD5, SHA-256 and perceptual hashing, CLI commands, and focused tests under `x_likes`.
