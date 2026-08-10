## Context

See `proposal.md` for motivation and scope. The catalog already provides platform-namespaced
accounts/posts, temporal account snapshots, raw-payload deduplication, media occurrences, external
link discovery, and managed assets. Its current import runner assumes a finite local file with a
digest, while remote provider work is paginated, rate-limited, credentialed, and resumable.

`CatalogWriter.store_raw()` currently stores import-associated raw observations without populating
their existing `platform_id`, and normalized tag and provider-artist tables do not yet exist.
`media_occurrences` has columns for `role` and `mime_type`, but the record/writer contract does not
persist them and has no declared file-size field. These gaps should be closed in the neutral model
rather than hidden inside provider-specific tables.

Pixiv is the central upstream source but does not offer a stable public API contract suitable for
this project. The pinned gallery-dl 1.32.2 implementation is therefore a behavioral reference and
fixture oracle, not a library contract. Danbooru documents its read API, authentication, rate-limit
headers, and user-agent expectations. AIBooru is close enough to exercise an instance-configured
Danbooru-family adapter, but fixture parity must still be verified independently.

## Goals / Non-Goals

**Goals:**

- Introduce one provider-neutral synchronization lifecycle used by native adapters.
- Preserve raw responses before normalization so schema drift is diagnosable and recoverable.
- Make every listing resumable and bounded by requests, pages, records, and elapsed time.
- Keep normalized provider records idempotent while preserving repeated observations and runs.
- Separate provider transport, normalization, and persistence so fixture tests require no network.
- Model tags, provider artist attribution, uploader accounts, and source references without
  collapsing their different meanings.

**Non-Goals:**

- A generic scraping framework or automatic discovery of arbitrary gallery-dl-supported sites.
- Media transfer, CAS publication, quality selection, or download retries.
- Automatic identity, creator, post, work, or visual-variation confirmation.
- Full-account enumeration without an explicit listing command and finite budgets.
- e621, Gelbooru, browser-cookie scraping, or a gallery-dl subprocess bridge.

## Decisions

### 1. Use a facade service over small adapter and persistence contracts

Add a `media_catalog.adapters` package with provider-neutral value types and separate `pixiv` and
`danbooru` subpackages. A public metadata synchronization facade owns run state, budgets,
transactions, diagnostics, and structured results. Provider clients only make authenticated HTTP
requests and return response envelopes; normalizers convert retained envelopes into neutral
records; the facade is the only layer allowed to invoke catalog persistence.

The core adapter operations are:

```text
fetch_account(stable_id)
fetch_post(stable_id)
list_account_posts(stable_id, cursor)
fetch_attribution(stable_id)       # supported by Danbooru-family adapters
```

Each response envelope includes provider operation, canonical secret-free request identity,
status, headers selected by an allowlist, response bytes, observation time, adapter/schema version,
and a typed continuation. Normalized pages contain records plus the continuation derived from that
exact response.

This keeps the contract smaller than the roadmap's eventual search/crawl surface. Adding search
later will extend the operation set without changing persistence semantics.

Alternatives considered:

- Let adapters write through `CatalogWriter`: rejected because transaction, budget, and checkpoint
  rules would be duplicated and provider code could bypass provenance.
- Import gallery-dl extractor classes: rejected because their internal/GPL contracts optimize for
  downloads and can change independently of the catalog model.
- One large adapter module: rejected because transport, normalization, and fixtures have different
  reasons to change and previous flat service decomposition proved hard to navigate.

### 2. Add remote runs rather than overloading file import runs

Add `remote_runs`, `remote_requests`, and `remote_checkpoints` (or equivalently named normalized
tables). A run records platform, operation, stable target, adapter version, immutable initial
budgets, mutable counters, status, timestamps, and a public diagnostic summary. A request records
attempt number, secret-free identity, status, selected rate-limit/retry metadata, timing, and its
raw observation. A checkpoint is keyed by run and operation target and stores an opaque,
versioned continuation plus the last committed page identity.

Budgets are immutable within a run. Resuming a paused or budget-exhausted operation creates a new
run linked by `resumed_from_run_id`, copies only the last committed compatible checkpoint, and
applies newly supplied finite budgets. This preserves what each execution was authorized to do
instead of rewriting its historical limits.

Continuations are opaque adapter values, JSON-encoded with an adapter/version discriminator. The
service never parses provider cursors to infer completion; the adapter explicitly returns either a
next continuation or completion. A resume refuses a checkpoint written by an incompatible adapter
version unless a provider-specific upgrader exists.

`import_runs` remains for immutable local sources. Reusing it was rejected because its non-null
source digest and size, whole-import transaction, and uniqueness rules do not describe a changing
remote collection.

### 3. Commit response capture before normalization, then atomically normalize and checkpoint

Each request follows two durable phases:

1. The service commits the request attempt and unmodified response bytes as a platform-associated
   raw observation. Authentication/token-exchange responses are transport secrets and are never
   captured as provider data.
2. A second transaction validates the retained response, upserts all normalized page records and
   provenance associations, updates counters, and advances the continuation checkpoint.

If phase 2 fails, the raw response and typed request outcome survive, but the previous checkpoint
does not move. Resume may normalize that retained response again before issuing another request.
Stable entity keys and observation association keys make replay idempotent.

A single transaction was rejected because rollback would discard the exact incompatible response
needed to diagnose provider schema drift. Advancing the checkpoint separately was rejected because
it could skip records after a crash.

### 4. Enforce budgets in a shared request gate

The facade checks all four budgets before every request and checks record/time budgets before page
commit. Counters count attempted HTTP requests, accepted provider pages, and normalized top-level
records. A page that would exceed the remaining record budget is not partially normalized: it is
retained raw, reported as budget-exhausted, and left before the same checkpoint. Callers may resume
with a larger explicit budget.

HTTP retries go through the same gate and count as requests. Retryable failures use bounded
provider policy and `Retry-After`/rate-limit state when supplied; sleeping never extends the elapsed
deadline. The Danbooru-family default will be conservatively below the documented maximum, with an
identifying user agent. No adapter may create an unbounded client retry loop.

Partial page persistence was rejected because it requires synthesizing a new provider cursor and
can make exact replay ambiguous.

### 5. Inject transport and time for deterministic fixture contracts

Provider clients accept an injected HTTP transport, clock, and sleeper. Production uses the
existing `httpx` dependency; contract tests use `httpx.MockTransport` with redacted response bytes,
headers, errors, and continuation sequences. Tests assert both normalized output and retained raw
provenance.

Fixtures record provider, capture date, redaction notes, adapter schema version, and expected
normalized JSON. Gallery-dl 1.32.2 output may be stored as a separate comparison oracle, but normal
tests neither import nor execute gallery-dl. Updating the gallery-dl pin or adapter schema requires
explicitly regenerating and reviewing affected comparison fixtures.

Recorded HTTP-cassette libraries were rejected because they tend to retain credentials and large,
unstable headers unless heavily filtered, while these contracts need deliberately minimal fixtures.

### 6. Keep credentials out of all durable identities

Built-in provider configuration names environment variables containing Pixiv refresh tokens and
Danbooru-family login/API keys. CLI commands select a configured provider/instance but never accept
secret literals. Configuration and diagnostics may expose the environment-variable name, never its
value.

Pixiv token exchange is isolated in the transport authenticator. Access tokens, refresh tokens,
authorization headers, cookies, and token responses are excluded from raw capture, request
identity, exceptions, and debug representations. The canonical request identity is constructed
from provider key, operation, stable target, HTTP method, endpoint template name, and allowlisted
non-secret parameters—not from the fully rendered authenticated URL.

A general secret-store abstraction is deferred; environment references are sufficient for this
local tool and can later be implemented by a different resolver without changing the adapter
contract.

### 7. Extend the neutral catalog for tags and provider attribution

Add platform-scoped `tags`, stable `post_tags`, and append-only `post_tag_observations`. A tag key
uses platform, category, and provider-normalized name; each observation retains exact provider
spelling, translation, position when supplied, observation time, and raw observation. This avoids
flattening categories or losing historical spelling while keeping current associations queryable.

Add neutral `attribution_entities` keyed by platform and provider-native attribution ID, plus
timestamped snapshots and provenance-bearing name, tag, and URL observations. These records are
not accounts and cannot be inserted into identity components. Danbooru artist objects use this
model; artist-category post tags remain tag associations and may link to an attribution entity only
when the provider supplies that relationship.

Uploader IDs create platform accounts and `uploader` post participation. Pixiv publishing users
create accounts and `author` participation. Neither role implies creator attribution.

Alternatives considered:

- Store tags and artists only in raw JSON: rejected because they must be searchable and usable as
  typed evidence.
- Treat booru artists as accounts: rejected because a community-maintained attribution record is
  not a login or proof of control.
- Make every tag spelling a separate stable tag: rejected because provider spelling history belongs
  to observations, while platform/category normalized identity supports idempotent associations.

### 8. Enrich media occurrences without creating assets

Extend `PostRecord`, post persistence, and queries to cover title, provider post type, provider
update time, and rating; reuse existing schema fields where present and add columns where absent.
Caption/description remains text content rather than being folded into the title.

Extend `MediaOccurrenceRecord`, writer logic, and queries to persist the existing occurrence
`role`/`mime_type` fields and a new nullable non-negative `declared_file_size`. Provider page
identity remains in `source_key`; `index` preserves order. `variants_json` stores a versioned,
validated provider-neutral list of alternate URL roles and supplied dimensions/MIME hints.

Pixiv uses a stable source key derived from artwork ID and page index. A Danbooru post uses its
stable primary media identity, retaining original/sample/preview URLs as variants. No adapter calls
`link_asset`, creates an asset location, or requests a media URL.

Provider-declared hashes remain occurrence assertions. The existing asset workflow alone may
create verified fingerprints after inspecting managed bytes.

### 9. Map provider semantics explicitly

Pixiv normalization uses stable numeric user and artwork IDs. Profile names are snapshot fields.
Artwork pages preserve provider order; tags preserve original and translated labels. Ugoira is a
metadata-only occurrence whose versioned variant metadata includes archive information and ordered
frame delays. Deleted/private/restricted responses become typed availability observations.

Danbooru-family normalization is instance-configured. Post tags keep their five categories,
uploader is a roleful stable account when supplied, artist records use attribution entities,
`source` and `pixiv_id` feed the existing typed external-reference/evidence path, and parent/child
references create directional post relations. `md5` is declared, never verified. AIBooru has its
own platform key and fixtures even when it reuses the same normalizer.

Provider URLs and fields are mapped from versioned fixture contracts rather than assumed to be
identical across instances. An incompatible AIBooru response fails as malformed instead of falling
through to permissive guesses.

### 10. Add provider-oriented CLI commands with stable structured results

Expose explicit commands for Pixiv account, artwork, and bounded account-artwork operations, and
for Danbooru/AIBooru post, artist, and bounded listing operations. Every live command requires
visible limits or uses documented finite defaults, supports stable JSON output, reports run ID and
termination reason, and never includes credentials or absolute private paths.

Live smoke tests are marked and skipped unless an explicit environment opt-in is present. They use
fixed public fixture identifiers, the smallest budgets, and no media requests. Unit and contract
tests fail if any unmocked network call occurs.

## Risks / Trade-offs

- [Pixiv's private App API changes or rejects the authentication flow] → Version every response
  contract, retain incompatible raw responses, isolate authentication, and require disabled live
  smoke tests before updating fixtures.
- [A provider page is larger than the remaining record budget] → Retain it raw but commit none of
  its normalized records; report the boundary and allow an explicit larger-budget resume.
- [Raw JSON contains personal or sensitive profile data] → Treat catalog files and fixtures as
  private, redact committed fixtures, never log payloads, and expose summaries rather than raw
  bytes in default CLI output.
- [Credentials leak through rendered URLs or exceptions] → Build request identities from
  allowlisted semantic fields, sanitize transport exceptions, and add sentinel-secret tests across
  database bytes, logs, diagnostics, and JSON output.
- [Tag normalization joins names that a provider considers distinct] → Scope keys by platform and
  category, preserve exact observed spellings, and keep the normalization algorithm/version
  explicit.
- [Booru artist URLs or source fields are stale or wrong] → Store them as observed evidence only;
  never auto-confirm identity, creator attribution, or post equivalence.
- [The first change becomes a general crawler] → Limit operations to fetch-by-stable-ID and bounded
  account/post listings; defer search expansion and all automatic traversal.
- [New migrations affect existing catalogs] → Make additions backward-compatible, backfill only
  fields with unambiguous provenance, and run fresh/upgrade/rollback/foreign-key tests.

## Migration Plan

1. Add a numbered migration for remote runs, requests, checkpoints, tag/observation tables,
   attribution entities/snapshots/links, raw-observation remote provenance, richer post metadata,
   and declared media file size. Preserve all existing IDs and constraints. Replace the existing
   Danbooru-compatible placeholder display name/null base URL with the explicit Danbooru instance
   metadata without changing its platform ID.
2. Extend records, writers, and queries. Existing local import paths continue to write null remote
   fields; existing media values remain unchanged.
3. Add shared adapter contracts, request gate, credential resolver, and synchronization facade with
   fixture-only tests before adding providers.
4. Add Pixiv normalization and client contracts, then Danbooru and AIBooru instance contracts.
5. Add CLI surfaces and disabled live smoke tests after offline behavior and secret-redaction tests
   pass.
6. Upgrade a copy of a schema-v4 catalog, run integrity/foreign-key checks, execute existing offline
   imports and asset queries, and verify rollback leaves the prior database usable if migration
   application fails.

Rollback before migration commit is transactional. After a successful migration, application
rollback requires restoring the pre-upgrade database backup because older binaries reject the
newer schema; remote metadata adds records but does not modify managed asset bytes.
