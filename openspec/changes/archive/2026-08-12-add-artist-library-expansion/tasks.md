## 1. Persistence contracts

- [x] 1.1 Add the numbered migration for immutable library expansion plans, count probes, execution/resume lineage, expansion-to-post provenance, remote-run origin association, constrained vocabularies and limits, foreign keys, uniqueness, and query indexes.
- [x] 1.2 Add validated record types and writer methods for expansion plan, probe, execution, and remote-run origin persistence without duplicating remote status or checkpoint state.
- [x] 1.3 Add fresh-schema, prior-version upgrade, failed-migration rollback, foreign-key, immutability, and integrity tests proving existing catalog IDs and metadata runs remain valid.

## 2. Typed target resolution and offline planning

- [x] 2.1 Implement closed account/attribution target and capability contracts with stable public references, revisions, redacted serialization, and fail-closed provider mappings.
- [x] 2.2 Implement seed resolution from account/post seeds, confirmed current review provenance, identity membership, authorship/attribution records, and explicit stable selections while excluding handles, uploaders, aliases, and free text as direct targets.
- [x] 2.3 Implement read-only deterministic expansion planning with bounded target choices, ambiguity handling, immutable limits, retained estimate provenance or unknown state, exclusions, adapter/schema versions, source revision, and plan digest.
- [x] 2.4 Add planner tests proving no network, catalog write, sidecar, review decision, or inferred identity occurs; cover Pixiv accounts, booru attribution, explicit overrides, ambiguity, unsupported targets, stale revisions, and invalid limits.

## 3. Provider capabilities and count probes

- [x] 3.1 Declare versioned Pixiv account-enumeration and Danbooru/AIBooru attribution-enumeration capabilities without changing account/attribution semantics or standalone adapter behavior.
- [x] 3.2 Implement the explicit bounded count-probe contract for providers with reliable fixture-backed count support, including sanitized identities, typed outcomes, raw retention, and timestamped count provenance; fail offline as unsupported where no capability exists.
- [x] 3.3 Add redacted fixture and injected-transport tests for supported, unavailable, authentication, rate-limit, malformed, and unsupported probe outcomes, proving a probe performs no listing or media request.

## 4. Expansion execution and resume

- [x] 4.1 Extend remote-run creation with an optional internal expansion origin while preserving existing `MetadataSyncService`, CLI, result JSON, retry, budget, checkpoint, and raw-retention behavior for standalone callers.
- [x] 4.2 Implement `ArtistLibraryExpansionService` plan validation/materialization and metadata-only execution through the existing synchronization service, rejecting stale plans before run creation or network access.
- [x] 4.3 Implement explicit resume lineage using only compatible committed remote continuations, with paused/failed/completed behavior derived from the linked metadata run and no parallel checkpoint state.
- [x] 4.4 Add interruption, kill-and-resume, stale-plan, typed provider failure, crash association, idempotency, and budget-boundary tests proving committed pages are neither duplicated nor skipped.

## 5. Offline inspection and downstream handoffs

- [x] 5.1 Implement read-only bounded list/show queries for targets, authority provenance, plans, probes, executions, resume lineage, estimates, limits, exclusions, linked remote state, and diagnostics.
- [x] 5.2 Derive stable target-scoped discovered-post/media filters, incomplete-detail counts, and paginated occurrence/variant selectors from explicit expansion-to-post associations without copying occurrence data or exposing unrelated catalog rows.
- [x] 5.3 Verify selectors feed the existing offline acquisition planner unchanged and that no expansion command invokes acquisition, chooses quality, downloads media, or writes managed storage.
- [x] 5.4 Add redaction and offline-query tests covering credentials, signed/rendered URLs, request material, raw payloads, private paths, deterministic pagination, and current-schema-only behavior.

## 6. CLI and documentation

- [x] 6.1 Add `catalog library plan|probe|run|resume|runs|show` with stable JSON and concise human output, finite limits, typed target selectors, explicit authority display, and bounded public errors.
- [x] 6.2 Add end-to-end CLI tests proving planning and inspection are read-only/network-free, probe and enumeration are separately explicit, and discovered posts receive no liked/bookmarked event or recursive expansion.
- [x] 6.3 Update the catalog usage guide, roadmap active/current state, and changelog with the artist-library workflow, example handoffs, safety boundaries, and troubleshooting for unknown estimates, ambiguity, pause, and resume.

## 7. Final verification

- [x] 7.1 Run focused migration, planner, adapter, service, query, CLI, privacy, and compatibility tests; run the full pytest, Ruff formatting/lint, and blocking ty gates.
- [x] 7.2 Validate the OpenSpec change strictly and run the required implementation review, address actionable findings, rerun affected gates, and record any genuine follow-up work in Beads.
