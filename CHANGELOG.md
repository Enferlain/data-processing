# Changelog

<!-- markdownlint-disable MD024 -->

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Rules:

- Use proper sub titles "Added", "Changed", "Removed" and "Fixed"
- Keep proper track of days for where entries should go
- Be concise but mention all changes without necessarily detailing each one

## [2026-10-07]

### Added

- **Pixiv engagement totals normalize (Bead `data-processing-cyp`, partial; OpenSpec change
  `extend-pixiv-engagement-facts`)** — artwork details emit bookmark and comment counts
  (from `total_bookmarks`/`total_comments`) that persist as post metadata observations
  through the shared page writer, reprocess-able from retained raw. The audit records the
  remaining scope precisely: `total_view` and the classification fields have no persistence
  homes; series membership has no representable object kind today (the same constraint that
  defers e621 sets — waits on the typed relationship model, bead `data-processing-t08`);
  and a related-works operation needs a new `AdapterOperation` value whose CHECK
  constraints on `remote_runs`/`remote_requests` require deliberate table rebuilds.

- **e621 post content facts normalize (Bead `data-processing-8jj`, OpenSpec change
  `extend-e621-post-content-facts`)** — description content lands as post text
  (`posts.text_content` — live-verified e621 descriptions embed the artist's original
  "From source:" caption, i.e. retained source content), the top-level seconds float
  lands as the occurrence's `duration_ms`, and URL-bearing `sample.alternates` enrich the
  variant metadata under `alternate:*` names with dimensions, extension/MIME, fps, and
  codec. Malformed shapes fail closed. Findings recorded in the audit: `locked_tags` and
  `change_seq` stay raw-retained (no persistence home), and the sets surface is verified —
  `/sets.json` does not exist; the real endpoint `/post_sets.json` returns 403 anonymously,
  so set membership needs the authenticated transport plus the typed grouping model
  (Bead `data-processing-t08`).

- **Materialize-a-seed gains the local-bytes phase (Bead `data-processing-8b2`, completed;
- **Materialize-a-seed gains the local-bytes phase (Bead `data-processing-8b2`, completed;
  OpenSpec change `add-materialize-seed` archived)** — `catalog seed create --file` ingests
  the file the operator holds: its content hash joins the bundle identity (changed bytes are
  a new seed), a declared MD5 is verified against the bytes before any write, and the file
  adopts through the existing managed-storage machinery into the designated `--media-root`,
  yielding verified SHA-256/MD5, detected dimensions, and a recorded perceptual hash linked
  to the stub's occurrence. The stub therefore seeds `external_post_id`, `declared_md5`, and
  `verified_md5` lookup planning exactly like a recorded post — requirement 1's non-recorded
  half now works end to end with innate image metadata preferred, per the decided design.

## [2026-10-06]

### Added

- **Non-recorded items gain a materialize-a-seed entry point (Bead `data-processing-8b2`,
  phase 1, OpenSpec change `add-materialize-seed`)** — the decided design's first half:
  `catalog seed create` ingests the operator's evidence bundle (one or more URLs where the
  item was found, optional note, optional declared MD5; all URLs must resolve to stable,
  pairwise-consistent post identities) and materializes a provenance-recorded stub post —
  the bundle retained as raw `operator_seed` import evidence, availability `unknown`, every
  URL as a `source_url` link and typed `provider_id` reference. The stub is an ordinary
  lookup seed (`external_post_id` planning accepts it exactly like a synced post),
  materialization is idempotent and decides nothing, and later real syncs enrich the stub
  in place. The local-bytes phase (hashing a held file into verified asset facts) remains
  open on the bead.

- **Gelbooru gains bounded reverse lookup and relationship normalization (Bead
  `data-processing-o6y`, OpenSpec change `add-gelbooru-bounded-lookup`)** — the last
  adapted provider with zero lookup capability now declares `source_post_url`,
  `declared_md5`, and `verified_md5` (rendered as exact credentialed DAPI `tags=` queries
  with digest-only request identities and pid page continuation under the shared limits;
  the HTML transport stays lookup-free), and the CLI accepts `--provider gelbooru` for
  plan/run/resume. Single-post DAPI fetches request `fields=tag_info`, so detail
  observations land typed tag categories (`tag`→general, `metadata`→meta, undocumented →
  unknown) instead of flat `unknown`; post `parent_id` normalizes as a directional
  `parent_of` relation and `title` lands on the post projection. The audit's
  favorites-dispute is resolved from references: gallery-dl's DAPI JSON `s=favorite&id=`
  works; Grabber's JSON path only refuses generic favorites syntax. Requirements 1 and 2
  are no longer blocked for gelbooru.

## [2026-10-05]

### Added

- **Danbooru-family post and artist fact normalization catches up (Bead
  `data-processing-unp`, OpenSpec change `extend-danbooru-post-artist-facts`)** — the
  adapter now emits fields the persistence layer already supported but no provider fed it:
  post score components (danbooru's negative `down_score` translated to the neutral
  downvote count), favorite count, and status flags as post metadata and flag
  observations; per-variant dimensions from `media_asset.variants` including the
  provider-native intermediate sizes (180x180/360x360/720x720) on the occurrence's
  variant metadata; and artist `group_name`/`is_banned`/created/updated on attribution
  snapshots. Malformed shapes for the new fields fail closed. Findings recorded in the
  metadata audit: danbooru post payloads carry no pool ids (pool grouping split out to a
  dedicated pools-surface bead), and `tag_count_*`/`has_children` are derivable from
  already-normalized tags and relations.

- **The identification-bridge hardening unit is completed (Bead `data-processing-zos`)** —
  e621's `external_post_id` now renders both known pixiv source URL spellings (bare and
  `/en/`) as separate bounded requests walked by the existing alias continuation, pinned by
  adapter tests and verified live through the mirrored control (danbooru post 12320097 →
  pixiv 150422897 → e621: two distinct requests, honest zero — not mirrored).
  `source_post_url` is demoted to weak evidence with the 0/10 probe result in the catalog
  guide's strategy-strength note, and the non-recorded-seed entry point is decided as a
  materialize-a-seed operation that ingests the full evidence bundle available at the time
  (innate image metadata first, supplied references at declared/asserted status) — recorded
  in the catalog plan §12 and the metadata audit.

- **Discovery-found references now seed stable-ID lookups (Bead `data-processing-zos`,
  partial)** — lookup planning read only sync-written `post_external_references`, so a
  pixiv URL discovered in a bookmark's text was invisible to the `external_post_id`
  strategy; the material query now unions the discovery chain
  (`link_observations` → `external_link_references` → `platform_references`), with a
  regression test. The live positive control then completed the first end-to-end
  identification hop: an X bookmark → discovery-found pixiv reference → Danbooru
  `pixiv_id:` metatag search → one result, landing as a pending review candidate.

### Fixed

- **The hosted-source metadata audit is delivered (Bead `data-processing-a3t`)** —
  [docs/plans/metadata-audit.md](docs/plans/metadata-audit.md) consolidates, per provider
  (danbooru/aibooru, gelbooru, e621, pixiv, X), what each source exposes (mined from
  gallery-dl and Grabber) against what the repo retains and normalizes, with every gap
  classified reprocess-able vs refetch. Headline findings: the strongest identification
  bridge (danbooru's first-class `pixiv_id` field and `pixiv_id:` metatag lookup) is
  already wired but never exercised; gelbooru has zero lookup capability despite
  server-side md5/source/id/parent search support; danbooru's adapter skips
  score/flag/pool fields the persistence layer already accepts; pixiv series and
  related-works are unnormalized relationship surfaces. Worklist filed as six beads.

### Fixed

- **e621 candidate lookups no longer reject the provider's response envelope (Bead
  `data-processing-7lt`)** — e621's `/posts.json` search wraps results in a `{"posts":
  [...]}` object while the lookup parser accepted only bare lists, so every e621 post lookup
  reported `malformed_response` regardless of results. The parser now unwraps the envelope
  (tag and alias endpoints keep their bare-list shape); fixture tests cover empty and
  populated envelopes, and the live probe seed that previously failed now returns a clean
  bounded page.

- **Link discovery no longer aborts on metadata-sync-attached links (Bead
  `data-processing-815`)** — discovery's end-of-run garbage collection deleted
  `external_links` that lacked discovery observations, but metadata sync legitimately
  attaches links through `post_external_references` and `account_external_links` without
  observations; after any provider metadata sync the whole `discover-links` run failed with
  a foreign-key violation. The collection now spares links referenced by any attach point,
  verified by a regression test and on the live catalog.

### Added

- **The supervised matching research spike is delivered (Bead `data-processing-8nj`)** —
  a bounded, manifest-driven research harness under `scripts/matching-spike/` (seeds,
  manifest builder, host-allowlisted fetcher, measurement runner) with private fixtures
  under `private-exports/matching-spike/`, and the redacted
  [matching spike evidence](docs/plans/matching-spike-evidence.md): 133 labeled pairs
  measured from real data — positives at phash@8 distance ≤ 10, negatives ≥ 22, two
  byte-identical cross-provider mirrors, thumbnails visually identical to originals at
  phash@8, and an empty same-artist false-positive class flagged as the key gap. Per the
  maintainer decision recorded in the evidence document, these measurements are research
  evidence only: catalog hashes remain identification metadata, and no similarity
  mechanism enters a product surface unless a generic, evidence-backed one is proven.

## [2026-10-04]

### Added

- **The audit-immutability sweep is completed (Bead `data-processing-5de`)** — migration 0013
  adds deletion guards for the pre-0012 update-only surfaces (expansion plans, probes,
  executions, and post associations; candidate-lookup requests; media-acquisition attempts),
  full immutability for acquisition verification records and source-report payloads (payloads
  previously protected only transitively; verifications previously unguarded), and primary-key guards on the recreated 0006/0007
  immutable-inputs triggers, matching 0012's stronger pattern. The mutation sweep again found
  zero delete statements on every guarded surface; the full suite passes under the triggers.

- **Kernel storage enforcement is closed (Bead `data-processing-ts5`)** — migration 0012 brings
  every audit surface the provenance-kernel spec names under storage-level enforcement: source
  reports, post-tag observations, provenance-event revisions, and review decisions are immutable
  and undeletable; provenance events, adoption attempts, candidates, evidence rows, and evidence
  links are never deleted but keep their legitimate current-field updates (event projection
  refresh, attempt re-recording, review state, rematerialized digests); remote requests are
  undeletable and immutable after insert except attaching — never swapping or detaching — their
  retained source report; and remote-run declared inputs (including transport identity) are
  immutable while state and counters advance. The change is archived as
  `close-kernel-storage-enforcement-gaps` with its requirement synced into the main
  provenance-kernel spec. A
  two-part writer audit (mutation statements and upserts) shaped the enforcement strengths so no
  audited write path breaks — the full suite passes under the triggers. Known consequence: a
  future purge/redaction feature must supersede or tombstone rows rather than delete history.

- **The export-projections milestone candidate is filed (Bead `data-processing-1oi`)** — bounded
  JSONL/CSV export projections over the evidence layer, an attribution-disagreement report, and
  per-field-source exports. A gap analysis against `docs/plans/raw_future_plan.md` found the
  catalog CLI has no export surface today and named this the highest-leverage non-Phase-D work
  toward the raw plan.

### Changed

- **The roadmap names the work and relationship model (kernel Phase D) as the leading next
  milestone**, with practical workflows free to take priority. A gap analysis against
  `docs/plans/raw_future_plan.md` split the milestone into independently landable halves: the
  schema half (artifact/work entities and the typed-relationship model, Bead
  `data-processing-t08`) and the supervised matching research spike, which gates only fuzzy
  matcher proposals and is rescoped to its own lower-priority bead (`data-processing-8nj`, P3).

## [2026-10-03]

### Added

- **The reviewed-target workflow lands (kernel Phase C)** — OpenSpec change
  `generalize-reviewed-target-workflow`: a new offline `catalog library capabilities` view reports
  the enumeration operations (or explicit unsupported markers) for any stable account or
  attribution target; target resolution now reports pending/rejected candidates as ineligible
  with their review state instead of silently filtering them; `catalog assets download-plan
  --library-plan` resolves acquisition selections from a committed expansion's associations
  offline under a fixed criteria set (variant, availability, eligibility, item limit), reporting
  `details_required` posts and `excluded_by_limit` counts, with the preview matching an equivalent
  explicit `--select` plan; and provider-path proof is complete for all four registered
  capabilities — new Danbooru and AIBooru checkpoint/resume coverage plus a per-provider
  pause/resume matrix test alongside the already-proven Pixiv and e621 paths. Upgrade note:
  resolution now emits `review_state_*` exclusions for unconfirmed candidates, which changes
  replan digests for seeds with such candidates — paused expansions created before the upgrade
  fail closed as stale on resume and must be re-planned and re-run.

- **The provenance-kernel direction is adopted** — a new `docs/plans/provenance-kernel.md` defines
  the domain-neutral vocabulary (source, source object, observation, provenance event, blob,
  representation,
  assertion, relationship, evidence, acquisition, run, review, projection) with uniform epistemic
  statuses (`observed`, `verified`, `derived`, `inferred`, `reviewed`), and maps every concept onto
  the existing catalog schema with status and action. The kernel is latent in today's tables, so
  this is a naming, spec, and boundary change — no data migration is planned. Milestone tracked as
  Bead `data-processing-u1d`.

- **The provenance-kernel capability spec is implemented** — OpenSpec change
  `add-provenance-kernel-spec` adds a standalone `provenance-kernel` capability with twelve
  requirements covering source identity, append-only source reports, provenance events,
  content-addressed blobs, declared/verified comparisons, typed relationships with epistemic
  status, the evidence ledger, append-only reversible review, the bounded run contract,
  storage-enforced audit immutability, projections, and kernel-invariant preservation. A
  schema-accuracy review corrected enforcement overstatements in the spec and the kernel plan's
  verified-mapping claims (immutability triggers cover only
  the listed tables; `remote_runs` inputs are immutable by convention today; acquisition runs use
  item/byte budgets with partial-based resume), added a precedence statement over domain-altitude
  capability specs, and neutralized media vocabulary in the provenance-event requirement;
  remaining storage-enforcement gaps are filed as Bead `data-processing-ts5`. The change is
  archived with the spec synced into the main specs, and the roadmap records the architectural
  pass complete.

### Changed

- **All adoption SQL now lives in StorageWrites** — the `adoption_items` read moved off the
  CatalogWriter facade into the persistence component (Bead `data-processing-v4i`); the facade
  method now delegates and no callers changed.

- **Single-family vocabularies and validators colocate with their record family modules** —
  acquisition, lookup, library (minus the cross-family origin-kind pair), and storage/adoption
  vocabulary-validator pairs moved from `records.common` into their family modules with the
  facade re-export surface unchanged (Bead `data-processing-ee0`); `records.common` now holds
  only cross-family primitives.

- **The roadmap's goal broadened** from a cross-platform media catalog to a source-aware gathering
  and provenance system with media as the first data family. The next milestone is the bounded
  provenance-kernel architectural pass (per-table mapping verification, an OpenSpec kernel
  capability spec, and cheap boundary re-homing absorbing the two ready persistence follow-ups);
  the reviewed-target workflow milestone follows it. Two principles were added: the durable
  database is the evidence layer with projections on top, and domain-neutral extraction requires a
  second consumer or a concrete workflow.
- **The media catalog plan is annotated** as the media-family domain plan under the kernel framing;
  its vocabulary remains authoritative for the media family.

## [2026-10-02]

### Added

- **The Gelbooru OpenSpec change is archived with specs synced** — the 10 delta requirements were
  merged into the main specs (new `gelbooru-metadata-adapter` capability spec with its seven
  requirements, one persistence-neutrality requirement into `media-catalog-core`, and transport-
  identity plus ephemeral-query-credential requirements into `remote-metadata-sync`), strict spec
  validation passes for all 14 capabilities, and the change moved to
  `openspec/changes/archive/2026-10-02-add-gelbooru-metadata-adapter/`.

- **Gelbooru DAPI continuations are fully scope-validated (task 3.4)** — listing continuations now
  carry every enumeration dimension — operation, listing target, query scope (unfiltered only, so a
  continuation claiming a tag query fails closed), sort (`id-desc`, the only pid-stable DAPI order),
  transport, direction (`forward`), page boundary (`pid`, `last_pid`, `limit`, and the last-seen
  post id for drift audit), and continuation/adapter/schema versions — and resume validates all of
  them before any network access. The continuation version bumped `gelbooru-pid-v1` → `gelbooru-pid-v2`
  so legacy unscoped checkpoints fail closed with a clear version error, the listing request
  identity/target embed the scope (`listing:<target>:id-desc:forward:<pid>:<limit>`), and boundary
  consistency requires `pid == last_pid + 1`. Thirteen new tests pin each dimension's rejection plus
  fail-safe handling of legacy request-target material; `gallery-dl`'s Gelbooru extractor (pid
  stepping and `sort:id`/`id:<N` ordering evidence) was used as the interaction reference.
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
- **The Gelbooru acceptance matrix reconciles all five real posts across transports** — five
  parametrized tests verify each captured post ID (12370900, 11605534, 10720246, 10791439,
  10791440) synchronizes through both DAPI and HTML, produces stable post reconciliation under
  a shared numeric identity, and retains independent observation histories; the three variation
  records each maintain distinct/pair semantics with two transport-identified raw observations
  per post.
- **Gelbooru privacy and network-isolation tests cover result objects and endpoint contact** —
  sync result objects, run metadata, and database rows are scanned for credential sentinels and
  contain no authenticated URLs; adapter-level tests prove only gelbooru.com is contacted with
  exactly one request per transport and no secondary media-host requests.
- **Gelbooru budget, resilience, and transport-mismatch tests use real catalog persistence** —
  budget exhaustion halts at the record boundary with raw retention but no committed page;
  database reopen and resume produces no duplicate posts; re-observation is idempotent while
  growing raw history; malformed DAPI responses produce typed `malformed_response` outcomes;
  transport mismatch is rejected before any network access.
- **Provider regression suites for Pixiv, Danbooru, AIBooru, and e621 pass** — existing
  adapter and metadata-sync test suites for all four providers confirm Gelbooru integration
  does not declare or trigger unrelated capabilities.
- **Disabled-by-default live smoke tests require explicit operator authorization** — one DAPI
  post and one HTML post smoke test are guarded by `GELBOORU_LIVE_SMOKE=acknowledged` and
  external credential environment variables, with hard request/body/record/time limits and
  assertions that no media host is contacted.

### Changed

- **Gelbooru schema audit timestamp corrected** — live captures use ctime-like format with timezone
  offset (`Wed Jul 30 10:16:34 -0500 2025`); the adapter normalizes to UTC ISO, and schema audit
  and adapter test expectations now match the actual normalized timestamps.

### Fixed

- **Scoped-continuation review: validation errors are never transient provider faults** — the
  shared request gate no longer wraps adapter `ValueError`s as `transient_provider`; local
  request-contract failures (incompatible continuation version or scope, malformed target, absent
  credentials) now propagate so the sync service records the run failed with the root cause in its
  diagnostic instead of masking it as a retryable provider fault. A stale pre-bump `gelbooru-pid-v1`
  checkpoint resume is pinned by a service-level test: permanent failure, truthful message, no
  transient classification. The DAPI post parser also now filters non-dict entries from wrapped
  `post` lists (matching the bare-array shape) so a garbage trailing entry can never crash
  continuation production with an untyped `AttributeError`. Two formerly untested scope branches
  (in-value continuation and adapter version material) gained rejection tests.
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
