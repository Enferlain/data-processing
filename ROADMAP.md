# Project roadmap

Last updated: 2026-08-12

## Goal

Build local-first tools that turn personal media activity into a durable, searchable, and
provenance-preserving collection.

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
| [Detailed catalog plan](docs/plans/cross-platform-media-catalog.md) | Architecture, data model, policies, research, risks, and long-term design |
| OpenSpec | Requirements and design for the active implementation change |
| Beads (`bd`) | Concrete ready, claimed, blocked, and follow-up work |
| [Changelog](CHANGELOG.md) | Dated history of completed changes |

When these differ, Beads is authoritative for task status, the active OpenSpec is authoritative for
the scope being implemented, and the detailed plan is authoritative for established architectural
constraints. Update this roadmap when a milestone starts, finishes, changes direction, or is
deliberately deferred.

## Current state

The `add-artist-library-expansion` milestone is complete and archived. The active
`add-e621-metadata-adapter` OpenSpec change under Bead `data-processing-7cy` is extending that
workflow with first-class e621 metadata, attribution lookup, artist-library enumeration, and
verified media acquisition. Implementation is paused at 15/30 tasks after completing the native
adapter, neutral persistence, metadata synchronization, CLI, resume, budget, and privacy work.
Candidate lookup is the next section.

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

## Active milestone: first-class e621 support

- Add a native e621 adapter under its documented descriptive User-Agent, authentication, pacing,
  page-size, keyset-pagination, availability, and privacy contracts.
- Preserve nested post/media facts, categorized tags, approved aliases, artist attribution,
  sources, relationships, uploader roles, and raw observations without inventing unavailable URLs.
- Extend bounded candidate lookup, artist-library expansion, target-scoped browsing, and explicit
  verified acquisition while keeping attribution separate from accounts and review conclusions.
- Keep Gelbooru separate until credentialed fixtures establish its undocumented response schema
  and an explicit personal-use policy decision permits bounded automation.

## Planned after the active milestone

### Broader provider coverage

- Add providers when they serve a concrete workflow and have a documented, bounded interaction
  policy. Likely candidates include e621, Gelbooru, and Mastodon-compatible sources such as Baraag.
- Prefer native metadata adapters for first-class providers.
- Consider a pinned gallery-dl subprocess bridge for unsupported sources or extraction assistance,
  but require all resulting files to pass the catalog's verification and CAS contract.
- Keep provider credentials external and preserve instance-specific IDs, policies, and failures.

### Operations and portability

- Add bounded JSONL/CSV exports intended for analysis and migration.
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
