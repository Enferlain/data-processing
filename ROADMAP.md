# Project roadmap

Last updated: 2026-10-04

## Goal

Build local-first tools that gather, retain, cross-reference, verify, and organize data from
heterogeneous sources while preserving provenance and uncertainty. Media is the first data family,
not the definition of the system: the durable database is the evidence layer, and consumer schemas
are projections over it. See the [provenance kernel plan](docs/plans/provenance-kernel.md) for the
domain-neutral vocabulary and how the current schema already embodies it.

The main catalog workflow should eventually let someone:

1. import an X like or bookmark;
2. identify the post, artist, and useful cross-platform references;
3. find plausible accounts or posts even when the X profile has no direct platform link;
4. review identity, source, authorship, and work relationships instead of accepting guesses;
5. inspect more works from a confirmed artist or source;
6. acquire selected media at the best known available quality;
7. retain raw observations, declared provider facts, locally verified facts, and review history;
8. revisit decisions as providers, accounts, and available evidence change.

The catalog is intentionally conservative. A matching name, uploader, tag, source URL, hash, or
similar-looking image can be evidence, but none of those facts silently becomes identity,
authorship, or work equivalence.

## Where project state lives

This roadmap is the short, evolving view of direction and milestone status. It does not replace
the other project records:

| Source | Responsibility |
| --- | --- |
| This roadmap | Current direction, completed capabilities, next milestone, and later work |
| [Provenance kernel plan](docs/plans/provenance-kernel.md) | Domain-neutral north star, kernel vocabulary, current-schema mapping, and generalization path |
| [Detailed catalog plan](docs/plans/cross-platform-media-catalog.md) | Media-family architecture, data model, policies, research, risks, and long-term design |
| OpenSpec | Requirements and design for the active implementation change |
| Beads (`bd`) | Concrete ready, claimed, blocked, and follow-up work |
| [Changelog](CHANGELOG.md) | Dated history of completed changes |

When these differ, Beads is authoritative for task status, the active OpenSpec is authoritative for
the scope being implemented, and the detailed plan is authoritative for established architectural
constraints. Update this roadmap when a milestone starts, finishes, changes direction, or is
deliberately deferred.

## Current state

The `add-artist-library-expansion` milestone is complete and archived. The `add-e621-metadata-adapter`
OpenSpec change under Bead `data-processing-7cy` is complete and archived.

The `add-gelbooru-metadata-adapter` OpenSpec change under Bead `data-processing-fql` is complete and
archived (2026-10-02): all 37 tasks implemented, two review passes addressed, delta specs synced into
the main `gelbooru-metadata-adapter` capability spec plus additions to `media-catalog-core` and
`remote-metadata-sync`, and all quality gates green.

On 2026-10-03 the provenance-kernel direction was adopted: the north star broadened from a
cross-platform media catalog to a source-aware gathering and provenance system with media as the
first data family. Existing schema, data, and tools are unaffected — the kernel is a naming, spec,
and boundary change for concepts the schema already implements. The provenance-kernel
architectural pass (Bead `data-processing-u1d`) is complete and archived the same day: the kernel
plan's mapping is verified against migrations 0001-0011, the standalone `provenance-kernel`
capability spec is synced into the main specs (now 15 capabilities), and the two persistence
follow-ups are absorbed. Its remaining storage-enforcement gaps were closed on 2026-10-04
(Bead `data-processing-ts5`, migration 0012).

The reviewed-target workflow milestone (kernel Phase C, Bead `data-processing-iso`) is complete
and archived (2026-10-03): the OpenSpec change `generalize-reviewed-target-workflow` was
implemented, reviewed by two independent review passes whose findings were folded in, and
archived with its delta specs synced into the main specs. All quality gates green.

Live task state can be checked with:

```bash
bd ready
bd list --status=in_progress
openspec list
```

## What works today

### X collection and catalog foundation — Complete

- `x-likes` imports liked posts from an exported X archive, enriches retained posts and accounts,
  and can optionally download and hash images.
- The platform-neutral `catalog` stores accounts and snapshots, posts and participants, likes and
  bookmarks, media occurrences, assets, raw observations, and import provenance in versioned
  SQLite migrations.
- Existing `x-likes` databases and xarchive bookmark JSON can be imported idempotently without
  changing their source data.
- Search, statistics, integrity checks, and public inspection output are available offline.

See the archived
[catalog foundation change](openspec/changes/archive/2026-08-05-build-media-catalog-foundation/)
and the [`catalog` guide](docs/tools/media-catalog.md).

### Cross-platform discovery and review — Complete

- URLs already present in profiles, posts, and retained raw records can be extracted and
  canonicalized without network access.
- Pixiv, X, Mastodon-compatible, Danbooru, Gelbooru, and e621 references retain platform,
  instance, object kind, identifier kind, source location, and recognizer version.
- URL aliases remain associated with one semantic reference instead of replacing each other.
- Account and post candidates are separate, evidence is explainable, and decisions are
  append-only and reversible.
- Only stable account identifiers can materialize reviewed identity membership; handles, names,
  hashes, uploader records, and artist tags remain evidence rather than conclusions.

See the archived
[cross-platform discovery change](openspec/changes/archive/2026-08-09-add-cross-platform-discovery/).

### Managed assets and verified acquisition — Complete

- Existing local media can be adopted into descriptor-safe, SHA-256-addressed managed storage.
- The catalog recalculates exact hashes, inspects supported images, records versioned perceptual
  hashes, preserves source provenance, and deduplicates identical bytes.
- Selected remote occurrences and variants can be downloaded explicitly with provider-aware host,
  redirect, credential, retry, resume, size, and time policies.
- Downloads use bounded staging, verification, quarantine, and atomic CAS publication.
- Provider-declared facts remain distinct from locally verified byte and image facts.
- Managed storage can be inspected and reconciled without exposing private paths.

See the archived [asset adoption](openspec/changes/archive/2026-08-10-adopt-local-assets-into-cas/)
and [remote acquisition](openspec/changes/archive/2026-08-11-download-selected-media-into-cas/)
changes.

### Pixiv and Danbooru-family metadata — Complete

- Pixiv profile, artwork, account-artwork listing, multi-page work, tag, and Ugoira metadata can be
  synchronized under explicit request, page, record, and time limits.
- Danbooru and AIBooru post, artist, uploader, categorized tag, relation, source, declared-hash,
  and pagination metadata can be synchronized without conflating attribution and identity.
- Runs retain sanitized requests, raw responses, normalized records, typed failures, and committed
  continuations. Metadata synchronization never implicitly downloads media.
- Media occurrences and their named variants can be browsed offline and fed into explicit
  acquisition plans.

See the archived [metadata adapter](openspec/changes/archive/2026-08-10-add-pixiv-danbooru-metadata-adapters/)
and [media browsing](openspec/changes/archive/2026-08-11-add-media-occurrence-browsing/) changes.

### e621 metadata, lookup, expansion, and acquisition — Complete

- The native e621 adapter handles post, tag, alias, artist, and bounded artist-tag listing
  operations with a descriptive User-Agent, optional external Basic auth, a one-second pacing floor,
  a 320-record page ceiling, typed outcomes, and raw-plus-normalized provenance.
- Dynamic tag categories, alias histories, artist attribution, uploader roles, relationships, and
  independent original/sample/preview availability remain distinct facts; unknown native categories
  stay recoverable instead of being silently mapped to general.
- Bounded lookup supports source URL, external post ID, declared/verified MD5, exact artist name,
  and approved alias strategies. Fuzzy/unrestricted text search is excluded and results never
  auto-confirm identity or authorship.
- A stable retained artist tag can seed explicit library expansion. Offline estimates use only an
  unambiguous current provider tag count; otherwise the estimate is unknown. Enumeration resumes
  by opaque `b<ID>` keysets, does not recurse or inherit liked/bookmarked state, and exposes
  target-scoped occurrence selectors for explicit acquisition.
- Explicit acquisition accepts only returned e621 original/sample/preview URLs on `static1` through
  `static9`, validates redirects, separates original claims from derivative verification, and uses
  staging, quarantine, and verified CAS publication.

Tags, aliases, and uploaders remain evidence rather than automatic identity/authorship. Generic
filtered counts and cross-database alias mapping are not available.
Metadata and expansion never fetch media, and live e621 smoke tests remain disabled by default.

### Gelbooru metadata — Complete

- Gelbooru post metadata can be synchronized through two explicit transports: credentialed JSON DAPI
  (single posts, tag metadata, bounded listings) and anonymous HTML (single-post pages).
- Both transports normalize fixture-proven fields — post identity, timestamps, rating, score,
  declared MD5, dimensions, tag-category evidence, uploader participants, and media variant
  references — into the shared neutral schema without downloading media or creating assets.
- DAPI credentials (`GELBOORU_USER_ID`/`GELBOORU_API_KEY`) are resolved from environment variables
  only, joined at the final HTTP boundary, and scrubbed from all durable and diagnostic surfaces.
- HTML transport requires no credentials, cookies, or browser automation. Challenge pages are
  detected and yield `authorization_denied`.
- Runs retain raw responses before normalization, commit pages atomically with checkpoint/resume for
  DAPI listings, and enforce a 2-second minimum interval with a 100-entry page ceiling.
- The current-projection policy ensures omission never erases retained history: DAPI and HTML
  observations coexist under one post identity, and disagreeing mutable facts resolve to the newer
  observation while both raw payloads preserve the audit trail.
- Live smoke tests are disabled by default and require explicit operator authorization
  (`GELBOORU_LIVE_SMOKE=acknowledged`). Credentials do not grant permission for broad crawling.

See the archived
[add-gelbooru-metadata-adapter change](openspec/changes/archive/2026-10-02-add-gelbooru-metadata-adapter/).

### Bounded candidate lookup — Complete

- An existing catalog account or post can seed explicit Danbooru or AIBooru lookups by supported
  source URL, embedded platform ID, exact hash, artist name, or alias strategy.
- Planning is offline and redacted; execution is finite, durable, resumable, and auditable.
- Lookup results feed the existing candidate and evidence ledger without overriding pending,
  confirmed, or rejected review decisions.
- Weak artist-name and alias results remain leads; exact post/hash evidence does not establish
  artist identity or authorship.
- Lookups do not recursively traverse results, enumerate newly found accounts, or download media.

See the archived
[bounded candidate lookup change](openspec/changes/archive/2026-08-12-add-bounded-candidate-lookup/).

## Working pipeline today

The pieces already support a deliberate, mostly manual end-to-end path:

```text
X likes / xarchive bookmarks
            |
            v
     local catalog import
            |
            v
 offline link discovery -----------+
            |                       |
            | no direct link        | stable direct reference
            v                       |
 bounded provider lookup           |
            |                       |
            +-----------+-----------+
                        v
             candidate review
                        |
                        v
          explicit metadata sync
                        |
                        v
              browse occurrences
                        |
                        v
           explicit acquisition plan
                        |
                        v
          verified managed CAS asset
```

The main gap is not another storage or provider primitive. It is a cohesive workflow that carries a
reviewed target through the lower half of this pipeline without requiring the user to manually
translate identifiers between several commands.

## Completed milestone: artist-library expansion

Turn the existing parts into an explicit workflow for growing a local library from a reviewed
artist or post lead.

Expected outcomes:

- start from a confirmed or explicitly selected stable account/post target;
- show which providers and metadata operations are available for that target;
- estimate and dry-run bounded account/work enumeration before network access;
- synchronize metadata through the existing adapter and checkpoint contracts;
- browse the discovered works without assigning liked or bookmarked state;
- select individual works, pages, or named variants for acquisition;
- reuse the existing verified download and managed-storage path;
- keep every handoff, exclusion, limit, and source observation inspectable;
- resume interrupted enumeration without recursively expanding into unrelated accounts or links.

This milestone should improve orchestration and usability rather than introduce a second crawler,
downloader, candidate ledger, or asset store.

## Completed milestone: provenance-kernel architectural pass

Name, verify, and spec the domain-neutral core that the schema already implements, so later
milestones build against a boundary instead of baking media assumptions deeper. Delivered
(2026-10-03):

- the kernel-to-schema mapping verified per table against migrations 0001-0011, with corrections
  folded into the kernel plan;
- a standalone `provenance-kernel` capability spec (twelve requirements) covering source and
  source-object identity, observation retention, provenance events, blobs, declared/verified
  comparisons, typed relationships with epistemic status, evidence and review ledgers, the bounded
  run contract, storage-enforced audit immutability, and projections — review-corrected so
  enforcement claims match what the schema actually guarantees;
- the two persistence follow-ups absorbed: all adoption SQL in StorageWrites, and single-family
  vocabularies colocated with their record family modules with the facade surface unchanged;
- the kernel vocabulary resolving `observations` (provenance events) versus `raw_observations`
  (source reports), and the spec boundary decided as a standalone capability.

Explicitly excluded, as planned: table renames, data migration, adapter behavior changes, and
speculative abstractions without a second consumer. Its storage-enforcement follow-up closed
2026-10-04 via migration 0012; see Current state.

## Completed milestone: reviewed-target workflow (kernel Phase C)

Carried a reviewed target through the lower pipeline without manual identifier translation, by
generalizing the existing `catalog library` engine rather than adding a second orchestration
surface. Delivered (2026-10-03, Bead `data-processing-iso`, archived change
`generalize-reviewed-target-workflow`):

- reviewed-target resolution reports pending and rejected account and post candidates as
  ineligible with their review state instead of silently filtering them, for account anchors and
  post anchors alike;
- an offline `catalog library capabilities` view reports the enumeration operations (or explicit
  unsupported markers) for any stable account or attribution target;
- `catalog assets download-plan --library-plan` resolves acquisition selections from a committed
  expansion's associations offline under a fixed criteria set (variant, availability, eligibility,
  item limit), with `details_required` and `excluded_by_limit` reporting and a selection digest
  identical to an equivalent explicit `--select` plan;
- provider-path proof complete for all four registered capabilities: Danbooru resume coverage and
  AIBooru execution and resume coverage added, a per-provider pause/resume matrix across Pixiv,
  Danbooru, AIBooru, and e621, all on the existing checkpoint contracts.

The workflow terminal is a ready acquisition plan; downloads remain an explicit separate action.
No new tables, engines, or provider primitives were added.

## Current milestone: none active

The provenance-kernel storage-enforcement gaps are closed (Bead `data-processing-ts5`, 2026-10-04,
migration 0012). Pick the next milestone from **Planned after the current milestone** when a
concrete workflow justifies it.

## Planned after the current milestone

### Broader provider coverage

- Add providers when they serve a concrete workflow and have a documented, bounded interaction
  policy. Likely candidates include Mastodon-compatible sources such as Baraag.
- Prefer native metadata adapters for first-class providers.
- Consider a pinned gallery-dl subprocess bridge for unsupported sources or extraction assistance,
  but require all resulting files to pass the catalog's verification and CAS contract.
- Keep provider credentials external and preserve instance-specific IDs, policies, and failures.

### Operations and portability

- Add bounded JSONL/CSV export projections intended for analysis and migration.
- Add explicit backup and restore workflows with integrity and count verification.
- Define retention and redaction policy for raw observations and failed network records.
- Improve schema, adapter-version, repair, and troubleshooting reports.
- Define the long-term boundary between `x-likes` direct storage and catalog-owned persistence.

### Discovery and maintenance

- Refresh previously observed accounts and posts under explicit policies instead of silently
  treating old metadata as current.
- Preserve account-handle and profile history when providers expose changes.
- Make unavailable, deleted, replaced, and moved records easy to revisit.
- Support bounded query-based discovery where provider capabilities allow it, without recursive or
  unlimited expansion.

### New data families

- Non-media payloads such as text, webpages, profiles, or dataset records enter through the same
  observation, run, and evidence contracts when a concrete workflow justifies them.
- No family-specific bypasses around provenance, bounded interaction, or review.

## Later research: supervised media and work matching

Image similarity is useful for proposing review candidates, but it is not reliable enough to be an
automatic truth mechanism. This work follows the artist-library workflow rather than blocking it.

Research should compare multiple signals and tools, including approaches used by czkawka and
similar duplicate finders:

- exact SHA-256 and MD5 equality;
- provider-declared hashes versus verified local hashes;
- perceptual hashes at multiple sizes and thresholds;
- resize and recompression robustness;
- crop-aware or region-based matching;
- color, structure, and feature-based metrics;
- false positives among visually similar but unrelated artwork;
- useful reviewer presentation and explanation.

The eventual model should be able to distinguish or leave unresolved:

- identical bytes;
- the same image re-encoded or resized;
- technical variants such as thumbnails or crops;
- meaningful edits such as text/no-text versions;
- different compositions or alternate versions of one work;
- ordered progression such as sketch to finished work;
- broader derivatives that should not be called the same work.

No metric or threshold should automatically establish artist identity, authorship, same-work,
source direction, or preferred quality. Those conclusions require provenance and review.

## Ongoing principles

- Local imports, planning, browsing, review, and verification remain offline by default.
- Every network operation is explicit, allowlisted, bounded, inspectable, and resumable where
  pagination or partial transfer makes that meaningful.
- Stable provider IDs are identity anchors; handles, display names, aliases, and bios are temporal
  metadata and evidence.
- Raw observations are retained so normalization can be reprocessed as adapters improve.
- Declared remote facts and locally verified facts remain distinct.
- A post relationship never silently proves an account relationship, and an account relationship
  never silently proves authorship of every post.
- Discovered content never inherits liked or bookmarked state.
- Better-quality selection remains explicit until its policy and evidence are trustworthy.
- Private paths, credentials, cookies, signed URLs, and raw payloads stay out of normal output.
- The durable database is the evidence layer; consumer schemas and exports are projections with
  stated policies.
- Extract domain-neutral concepts only when a second consumer or a concrete workflow needs them;
  typed schemas over a small kernel, never a generic entity-attribute-value soup.

## Updating this roadmap

When work begins:

1. create and claim the concrete Beads issue;
2. create an OpenSpec change when behavior, schema, or architecture needs a reviewed contract;
3. update **Current state** and, if necessary, the ordering or scope of the next milestones.

When a milestone finishes:

1. close its Beads issues after verification;
2. sync and archive its completed OpenSpec change;
3. record notable behavior in the changelog;
4. move the roadmap item into **What works today** and name the new next milestone.

Avoid detailed task checklists here. If work can be claimed, blocked, assigned, or closed, it
belongs in Beads.
