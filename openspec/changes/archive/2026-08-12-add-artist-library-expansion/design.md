## Context

The catalog already has four independent pieces needed by this change:

- reviewed account/post candidates and materialized stable account identities;
- Pixiv account-artwork and Danbooru-family bounded listing adapters;
- durable metadata runs with raw retention, limits, checkpoints, and resume;
- offline media browsing and explicit verified acquisition.

The current CLI exposes each piece separately and requires the user to translate a reviewed target
into a provider-specific metadata command, then reconstruct browse and acquisition selectors. The
existing metadata run records also do not explain which catalog seed or review/explicit selection
authorized an enumeration. See `proposal.md` for motivation and the capability spec for observable
behavior.

## Goals / Non-Goals

**Goals:**

- Add a thin orchestration layer over existing review, adapter, metadata, browse, and acquisition
  boundaries.
- Make account and attribution expansion distinct in types, persistence, and output.
- Make offline planning, optional probing, execution, resume, and downstream selection separately
  explicit and inspectable.
- Preserve current standalone CLI and service behavior while adding origin context to metadata runs.

**Non-Goals:**

- General recursive crawling, automatic link traversal, background scheduling, or unbounded search.
- New providers, gallery-dl integration, similarity matching, work grouping, or quality ranking.
- Automatic identity/authorship/source confirmation or interpreting a booru artist as an account.
- A second metadata normalizer, checkpoint engine, media browser, downloader, or asset store.

## Decisions

### 1. Use typed catalog targets, not provider command strings

Introduce an immutable `ExpansionTarget` with a closed target kind (`account` or `attribution`),
internal catalog ID, provider/instance key, stable native identifier, target revision, and adapter
capability key/version. The public selector uses the internal typed reference; rendered provider
parameters remain private to the adapter/orchestrator.

Pixiv stable users map to account enumeration. Danbooru-family artist entities map to attribution
enumeration even though the existing adapter internally routes listing through its current listing
operation. Uploader accounts, handles, aliases, and text are not silently converted to targets.

Alternatives rejected:

- Reusing only `platform:native-id` strings loses account-versus-attribution semantics and catalog
  revision checks.
- Treating Danbooru artists as accounts would violate the established identity model.
- Adding a generic free-text crawl target would bypass review and bounded candidate lookup.

### 2. Resolve a seed to choices, then require one selected target

Planning accepts an account or post seed and an optional target selector. The resolver gathers
eligible stable targets from the seed itself, confirmed current relationships/identity membership,
post authorship/attribution records, and explicit catalog targets. It returns deterministic choices
and their provenance. If more than one is eligible, execution remains unavailable until the user
selects one.

Two authority modes are stored:

- `confirmed`: references the current review decision/evidence path that supports the handoff;
- `explicit`: records the user's direct selection and optional bounded note, but creates no review
  decision and asserts no identity or authorship relationship.

This makes overrides useful without weakening the review ledger.

### 3. Planning is a pure snapshot; execution materializes it

`plan_library_expansion` opens the catalog read-only, resolves the seed and target, reads provider
capabilities and retained counts, applies finite limits, and produces a redacted deterministic
digest. It performs no write and no network request. Counts carry value, observation time, and
source; absence is represented as `unknown`.

Before execution, the service recomputes the private plan material and rejects changes in seed or
target revision, authority, capability/version, adapter/schema version, limits, or target identity.
Only an accepted plan is persisted. This follows the existing candidate-lookup and acquisition
stale-plan pattern.

### 4. Persist orchestration provenance without duplicating remote-run state

Add normalized expansion tables rather than copying metadata checkpoints or results:

- `library_expansion_plans`: immutable seed, target, authority, capability, limits, estimate,
  versions, digest, and creation time;
- `library_expansion_probes`: optional explicit count-probe observation/outcome and raw observation
  reference;
- `library_expansion_executions`: execution/resume lineage and a unique reference to the underlying
  `remote_run`;
- `library_expansion_posts`: immutable associations from an execution and typed target to each post
  committed from its normalized listing pages, with raw-observation provenance.

The metadata service accepts an optional internal origin descriptor when it creates a remote run,
allowing the expansion execution and remote run to be associated at creation rather than repaired
after a crash. Its existing public calls, default behavior, result JSON, raw retention, and
checkpoint semantics remain unchanged. Expansion queries join to remote-run/checkpoint state rather
than maintaining parallel status or continuation columns.

Alternatives rejected:

- Encoding provenance in remote-run target strings is ambiguous, hard to query, and risks exposing
  private material.
- Copying remote-run status/checkpoints into expansion tables creates two sources of truth.
- Linking only after synchronization returns leaves an unassociated run after interruption.

### 5. Declare expansion and count capabilities separately

Add a small capability contract keyed by provider/instance and target kind. It declares the
enumeration operation, capability version, supported target type, and whether a bounded count probe
exists. The adapter remains responsible for rendering provider requests and interpreting counts.

A probe is its own one-request/time-bounded operation with sanitized request identity, retained raw
response, and typed outcome. It never substitutes for the offline plan and never starts listing.
Providers without a reliable count endpoint report `unsupported`/`unknown` without network access.

### 6. Compose the existing executor and persistence services

`ArtistLibraryExpansionService` validates/materializes the plan and invokes
`MetadataSyncService.synchronize` with the selected adapter operation, stable target, existing sync
limits, optional prior compatible remote run, and the expansion origin. Page normalization and
persistence remain adapter/metadata-service responsibilities.

Resume creates a new execution lineage entry and uses the existing committed continuation checks.
The expansion layer does not inspect or mutate cursors and does not retry completed runs as though
they were paused.

### 7. Downstream handoffs are selectors, not hidden execution

Expansion detail uses `library_expansion_posts`, not tags, names, uploaders, or URLs, to derive a
target-scoped discovered-post view. It joins those posts to available occurrences and returns stable
`media_occurrence_id:variant` selectors, bounded and paginated using existing media-query semantics.
The association stores provenance, not a second copy of post or occurrence data.

Provider listings are allowed to return sparse post summaries. Pixiv's current fixture, for
example, contains IDs without occurrence URLs. Such posts are reported with `details_required`
and remain available for a later explicit ordinary post-detail synchronization; expansion does not
silently fan out into one request per listed post. Danbooru-family listing pages may already contain
full occurrence data, which becomes immediately browseable through the same association.

Acquisition remains a separate call to the existing planner/service. The expansion API may format
selectors for convenience but never invokes acquisition implicitly.

### 8. Add a cohesive `catalog library` facade

Expose `plan`, `probe`, `run`, `resume`, `runs`, and `show` under `catalog library`. Planning and
queries accept a catalog path and use the current-schema read-only connection path. Network commands
instantiate only the selected provider adapter and database writer after validation.

Machine output is stable, bounded JSON; human output highlights target type, authority, estimates,
limits, exclusions, remote-run state, browse selector, and next explicit command. Neither form emits
rendered provider URLs, credentials, raw payloads, or private paths.

## Risks / Trade-offs

- **[Provider count semantics differ or become stale]** → Store count provenance/time, distinguish
  exact provider counts from retained estimates, and permit `unknown` rather than treating a count
  as an execution guarantee.
- **[Explicit selection could be mistaken for confirmed identity]** → Persist and display authority
  mode everywhere; never write to the review or identity tables from expansion.
- **[Attribution enumeration can include reposts or misattributed works]** → Preserve provider
  attribution and source observations; discovered posts remain browse/review candidates, not
  authorship truth.
- **[Wrapper and remote run can diverge on crash]** → Create the association with the remote run at
  run creation and derive status/checkpoints from the remote record.
- **[Large libraries make result presentation expensive]** → Use immutable budgets, keyset
  pagination, bounded related collections, and existing indexed post/occurrence queries; add indexes
  only where measured query plans require them.
- **[A provider adapter cannot safely enumerate one target type]** → Capability declarations fail
  closed and planning produces an exclusion rather than guessing a provider query.

## Migration Plan

1. Add a numbered migration for expansion plan/probe/execution/post provenance, foreign keys,
   immutable limit checks, authority/target vocabularies, uniqueness, and indexes; existing rows
   require no backfill.
2. Add records/writer/query contracts and fresh/upgrade/rollback/integrity tests.
3. Add typed target resolution and pure offline planning before enabling any network command.
4. Add provider capability/count-probe adapters and integrate the optional origin descriptor into
   remote-run creation without changing existing standalone behavior.
5. Add execution/resume composition, downstream browse/acquisition selectors, CLI, tests, and docs.
6. Rollback by reverting application code before the migration is applied; after migration, older
   binaries correctly reject the newer schema and the additive tables can remain intact.
