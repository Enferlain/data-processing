# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Rules:
- Use proper sub titles "Added", "Changed", "Removed" and "Fixed"
- Keep proper track of days for where entries should go
- Be concise but mention all changes without necessarily detailing each one

## [2026-08-12]

### Added

- **The catalog can perform bounded cross-platform candidate lookups** — added explicit plan, run, resume, list, and show workflows for provenance-rich Danbooru and AIBooru source-URL, platform-ID, hash, artist-name, and alias searches without treating results as identity or authorship proof.
- **Candidate lookups are durable, finite, and review-oriented** — added immutable limits, sanitized request attempts, retained raw observations, checkpoints, typed provider outcomes, result associations, and evidence integration with the existing manual match-review ledger.

### Changed

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
