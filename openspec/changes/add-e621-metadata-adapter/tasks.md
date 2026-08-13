## 1. Schema and compatibility audit

- [x] 1.1 Map every required e621 post, media, tag-category, alias, attribution, uploader, source, relationship, score, flag, and availability fact to current catalog records/tables and document exact representability gaps in the implementation notes.
- [x] 1.2 Add characterization tests for existing Danbooru/AIBooru metadata, lookup, expansion, media-query, acquisition-policy, CLI, raw-retention, and resume behavior before extracting shared provider boundaries.
- [x] 1.3 If and only if task 1.1 proves gaps, add the smallest numbered neutral migration plus validated records/writers/queries and fresh-schema, prior-version upgrade, failed-migration rollback, foreign-key, immutability, doctor, and ID-preservation tests.

## 2. e621 contracts, fixtures, and request policy

- [x] 2.1 Add the separate `media_catalog.adapters.e621` package with versioned provider, adapter, schema, continuation, capability, credential-reference, User-Agent, page-size, and minimum-interval contracts.
- [x] 2.2 Commit redacted fixtures for a normal post, deleted post, nondeleted null-media post, tag, approved/active alias, artist, first/continuation listing pages, unknown ID, malformed response, authentication/authorization failure, 429/503 rate behavior, and video/animation metadata when fixture-backed.
- [x] 2.3 Implement secret-free anonymous and optional Basic-auth request rendering, exact host/path/parameter admission, descriptive User-Agent enforcement, one-second minimum pacing, typed status outcomes, and bounded diagnostic/retry metadata.
- [x] 2.4 Add injected-transport tests proving exact request counts and shapes, credentials never enter durable identities/output, provider pacing cannot be weakened, and default tests make no network or media requests.

## 3. Post, attribution, and pagination normalization

- [x] 3.1 Implement strict fetch/normalization for explicit e621 posts, retaining raw responses and stable post timestamps, rating, score/counts, sources, pools, flags, uploader role, and parent/child relationships without inferring review conclusions.
- [x] 3.2 Normalize original, sample, and preview representations with independent availability/dimensions, apply declared MD5/size/type/dimensions only to the original, and reject MD5-derived URL reconstruction.
- [x] 3.3 Normalize dynamic tag categories, exact tag records, alias status/provenance, and artist records/URLs as attribution evidence distinct from accounts and uploaders.
- [x] 3.4 Implement bounded older-ID listing with opaque versioned `b<ID>` continuations, maximum page size 320, target/direction/version validation, and no durable numeric-page dependency.
- [x] 3.5 Add adapter contract tests for idempotent reobservation, unknown fields/raw recovery, null URL versus deletion, dynamic categories, malformed required fields, continuation mismatch, boundary admission, and no implicit pool/note/media fan-out.

## 4. Remote synchronization and CLI metadata workflow

- [x] 4.1 Wire e621 through the existing remote synchronization executor and normalized page writer so raw response, normalized facts, counters, and continuation commit atomically without changing standalone providers.
- [x] 4.2 Add explicit CLI operations for e621 post, attribution/tag or artist metadata, alias metadata where needed, and bounded attribution-post listing/resume with stable human/JSON output and external credential configuration guidance.
- [x] 4.3 Add interruption, retry, malformed, authentication, rate-limit, request/page/record/time boundary, kill-and-resume, checkpoint idempotency, privacy, and compatibility tests across service and CLI surfaces.

## 5. Candidate lookup integration

- [ ] 5.1 Extract the minimal provider-neutral lookup planning/configuration boundary needed to remove hardcoded Danbooru identity while preserving all existing Danbooru/AIBooru plan digests, exclusions, requests, persistence, candidates, and resume behavior.
- [ ] 5.2 Declare and implement e621 source-post URL, external post ID, declared MD5, verified MD5, exact artist-name, and approved artist-alias lookup strategies; explicitly exclude arbitrary fuzzy/unrestricted text search.
- [ ] 5.3 Normalize e621 lookup results into post candidates or attribution/weak leads with raw provenance, keeping hashes, tags, aliases, uploaders, artist records, and post matches from auto-confirming identity or authorship.
- [ ] 5.4 Add offline-plan, stale-material, request-budget, pagination/resume, result-idempotency, rejected-decision preservation, alias-status, privacy, and Danbooru/AIBooru regression tests plus CLI provider routing.

## 6. Artist-library expansion integration

- [ ] 6.1 Register a versioned e621 attribution enumeration capability that resolves only stable retained attribution targets and privately renders the exact canonical artist tag.
- [ ] 6.2 Add offline retained-count estimation only for an unambiguous current canonical artist-category tag observation; keep aliases, filters, missing/stale observations, and arbitrary searches unknown without a probe/listing request.
- [ ] 6.3 Execute and resume e621 expansions through existing origin/checkpoint/post-association contracts, preserving `b<ID>` lineage, target-scoped browsing, no recursive expansion, and no liked/bookmarked inheritance.
- [ ] 6.4 Add explicit/confirmed authority, ambiguity, stale tag/alias/capability, count provenance, paused resume, sparse/unavailable media, target-scoped selectors, privacy, CLI, and existing-provider regression tests.

## 7. Media acquisition integration

- [ ] 7.1 Add a versioned e621 media policy for returned HTTPS original/sample/preview URLs with a bounded verified `staticN.e621.net` host rule, redirect validation, descriptive User-Agent, response-type expectations, and no URL derivation.
- [ ] 7.2 Ensure original variants compare verified output with declared original MD5/size/type/dimensions while sample/preview variants retain only their own verified representation facts.
- [ ] 7.3 Add plan/execution tests for allowed and rejected hosts/redirects, null URLs, original claim match/mismatch, sample/preview claim separation, interruption/quarantine/CAS reuse, redacted output, and zero implicit acquisition from metadata or expansion commands.

## 8. Documentation and final verification

- [ ] 8.1 Update the catalog guide, roadmap current/completed capabilities, and changelog with e621 configuration, metadata, lookup, expansion, browsing/acquisition handoffs, limitations, pacing, privacy, and troubleshooting.
- [ ] 8.2 Add disabled-by-default live e621 metadata smoke tests with descriptive User-Agent and hard request/record/time limits; verify they never request returned media URLs and document how to opt in safely.
- [ ] 8.3 Run focused adapter, schema, synchronization, lookup, expansion, media, acquisition, CLI, privacy, migration, and compatibility tests; run changed-file Ruff formatting plus repository Ruff, blocking ty, and full pytest gates.
- [ ] 8.4 Validate the OpenSpec change strictly, run the required implementation review, address actionable findings, rerun affected gates, update/close Beads work, and sync/archive only after every task is complete.
