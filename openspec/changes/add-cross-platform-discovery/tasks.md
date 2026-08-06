## 1. Schema and normalized contracts

- [ ] 1.1 Add a numbered migration for discovery runs, canonical links, link observations, platform references, identities/memberships, typed account/post candidates, shared evidence, characteristics, and append-only decisions with foreign keys, checks, uniqueness constraints, and query indexes.
- [ ] 1.2 Add immutable normalized records and validators for source contexts, platform instances, object kinds, candidate/relation kinds, evidence stance/strength, review states, and version identifiers.
- [ ] 1.3 Add migration and constraint tests covering fresh creation, upgrade from the foundation schema, rollback on failure, future-version rejection, instance-namespaced IDs, endpoint-kind rejection, foreign-key integrity, and unchanged pre-existing data.

## 2. Offline URL extraction and recognition

- [ ] 2.1 Implement conservative versioned URL parsing and canonicalization that retains original query/fragment data and rewrites only allowlisted non-semantic components.
- [ ] 2.2 Implement source-specific extractors for normalized account fields and supported retained X/xarchive bio, text, entity, card, quote, and source locations, including stable source contexts and JSON paths.
- [ ] 2.3 Implement a recognizer registry for direct X account/post, Pixiv user/artwork, and configured Danbooru-family post/artist/media-asset routes with numeric IDs, legacy aliases, and instance hostnames handled explicitly.
- [ ] 2.4 Add table-driven recognizer/canonicalizer tests for equivalent aliases, ambiguous query parameters, invalid URLs, shorteners, personal/link-hub URLs, Pixiv numeric IDs, and colliding native IDs on different booru instances.

## 3. Link discovery persistence and queries

- [ ] 3.1 Extend the catalog writer to store discovery runs, canonical links, per-context link observations, recognized references, unresolved states, counts, and bounded diagnostics through one validated persistence contract.
- [ ] 3.2 Implement the offline discovery service with stable digests, version-aware rescans, transactional run lifecycle, per-entity reconciliation, and preservation of distinct contexts that share one canonical URL.
- [ ] 3.3 Implement link queries and filters for source account/post, source context, target platform/instance, object kind, and resolution state with stable human and structured result models.
- [ ] 3.4 Add tests for repeated and upgraded discovery runs, original/canonical round-tripping, raw provenance, multiple contexts, malformed-record diagnostics, private-path redaction, source immutability, and denial of all socket connections.

## 4. Typed candidate and evidence generation

- [ ] 4.1 Implement separate account and post candidate persistence with FK-safe local/reference endpoints, stable symmetric/directed keys, explicit subject-to-target relation orientation, self-link rejection, current review state, and identity-preserving target reconciliation when external references later resolve locally.
- [ ] 4.2 Implement immutable shared evidence plus typed joins and deterministic versioned scoring whose visible components remain separate from review state.
- [ ] 4.3 Implement link-derived account and post candidate generation, keeping profile identity evidence, post-source evidence, booru artist/uploader semantics, and provider-observed post relations distinct.
- [ ] 4.4 Implement the initial broad post relation families and repeatable characteristics so sourced-from, same-work, repost-of, variant-of, derived-from, unresolved, technical variation, and progression evidence can be represented manually without downloading bytes, calculating hashes, or automatically classifying images.
- [ ] 4.5 Add tests for candidate/evidence idempotency, X-subject-to-Pixiv-target directionality, symmetric-pair deduplication, self-link suppression, one link supporting different claims, weak-name evidence remaining separate, high scores remaining pending, unknown transformations, no image computation, unchanged provider post relations, and no automatic creator/account inference.

## 5. Review history and identity membership

- [ ] 5.1 Implement append-only typed decision services that validate state transitions, retain reviewed evidence generation and notes, expose current state efficiently, and preserve earlier decisions on reconsideration.
- [ ] 5.2 Implement explicit-confirmation identity creation/membership with decision provenance, metadata-empty account materialization from stable account references, reference reconciliation, safe extension of an existing identity, and conflict reporting instead of silent identity-group unions or transitive pair confirmation.
- [ ] 5.3 Add tests for confirm, reject, reconsider, rediscovery after rejection, concurrent/stale review protection, stable candidate/evidence/history across target reconciliation, no fabricated target profile fields, identity conflict handling, non-transitive confirmation, and confirmation that leaves existing accounts/posts/raw provenance unchanged.

## 6. CLI, documentation, fixtures, and verification

- [ ] 6.1 Add discover-links, link listing, candidate listing/show, and candidate review commands with documented filters, stable JSON documents, bounded errors, and tested exit codes.
- [ ] 6.2 Extend the catalog usage guide with offline discovery, evidence interpretation, review semantics, identity caveats, unresolved-link handling, backups, privacy, and the boundary before future network adapters or image matching.
- [ ] 6.3 Add synthetic/redacted fixtures representing account bio links, post source links, different handles, Pixiv multi-page works, booru artist/uploader separation, instance collisions, unresolved link hubs, and uncertain image variations; incorporate user-selected public examples only as redacted URL/expected-relation cases with no live fetch dependency.
- [ ] 6.4 Run formatting, lint, the full Python 3.13 suite, package build/install CLI smoke tests, strict OpenSpec validation, and offline discovery/idempotency/integrity smoke tests against a user-selected catalog copy.
