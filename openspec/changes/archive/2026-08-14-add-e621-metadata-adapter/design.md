## Context

The catalog already has provider-neutral request/response/page contracts, bounded remote runs,
atomic raw-plus-normalized page commits, candidate lookup, artist-library expansion, media browsing,
verified acquisition, and managed CAS storage. e621 URLs are recognized, but no native adapter,
capability declarations, fixtures, or media policy exist.

Current first-party research verifies that e621 provides documented JSON post, tag, and tag-alias
contracts; ID-keyset pagination; optional Basic API authentication; a maximum page size of 320; a
hard two-requests-per-second ceiling with sustained traffic expected at or below one request per
second; and a required descriptive application User-Agent. Returned post objects have nested file,
sample, preview, tags, flags, relationships, and score structures. Both deleted and non-deleted
posts can have null media URLs. No documented generic filtered-post count endpoint exists.

gallery-dl and tag-workspace are implementation references only. They confirm useful fixture shapes
but their downloader-specific URL reconstruction, broad exception handling, query-string auth,
X-Total assumptions, and unbounded loops are not contracts for this repository.

## Goals / Non-Goals

**Goals:**

- Fit e621 into the existing neutral adapter, synchronization, lookup, expansion, browsing,
  acquisition, and review boundaries.
- Preserve provider facts and raw observations without inventing unavailable URLs or conclusions.
- Make every remote operation explicit, finite, paced, resumable, secret-safe, and fixture-backed.
- Keep exact provider attribution, uploader roles, external accounts, and review decisions distinct.

**Non-Goals:**

- Implement Gelbooru, generic Booru-on-Rails support, favorites, pools/notes fan-out, bulk exports,
  recursive crawling, automatic detail hydration, or background scheduling.
- Reconstruct absent e621 media URLs from MD5 paths or depend on gallery-dl at runtime.
- Infer identity, authorship, same-work, source direction, or preferred quality automatically.
- Add similarity or perceptual-match decisions.

## Decisions

### 1. Implement a separate native e621 adapter

Add `media_catalog.adapters.e621` with its own configuration, transport, response normalizer,
capability declarations, and fixture version. It implements the existing neutral adapter and lookup
protocols but does not subclass the Danbooru adapter: e621's nested schema, artist/tag model,
authentication, page ceiling, and keyset behavior are materially different.

The adapter supports explicit post fetch, attribution/tag fetch, alias fetch needed by lookup,
artist metadata fetch where fixture-backed, and artist-tag post listing. Optional pools and notes
embedded in post metadata are retained as IDs/counts, but the adapter does not fan out to fetch
pool or note bodies in this change.

Alternatives rejected:

- Configuring e621 as another `DanbooruInstance` would hide incompatible schema and policy.
- Invoking gallery-dl would couple metadata persistence to downloader output and retry semantics.
- Building a generic booru base first would speculate about Gelbooru compatibility before its
  credentialed schema is known.

### 2. Centralize a versioned e621 request policy

Define one provider configuration used by metadata, lookup, and expansion adapters: canonical API
host, descriptive User-Agent template, page-size maximum 320, minimum interval one second,
credential reference names, adapter/schema/capability versions, and typed status classification.
The request gate remains the admission authority for request and elapsed-time budgets. The adapter
adds provider headers and optional ephemeral Basic auth immediately before transport.

HTTP 401 maps to authentication-required, 403 to authorization-denied, 404 for explicit objects to
unavailable, 429 to rate-limited, and 503 to rate-limited when provider evidence identifies a rate
limit or otherwise transient-provider. Raw responses are retained before normalization whenever a
request occurs. Diagnostics never include request URLs, auth values, descriptions, or source text.

Alternatives rejected:

- Browser impersonation conflicts with e621's documented User-Agent policy.
- Query-string credentials increase secret exposure risk; Basic auth is the preferred contract.
- Relying only on the generic retry interval could permit a caller to weaken provider pacing.

### 3. Use returned post data and explicit availability; never synthesize URLs

Normalize each e621 post into a stable post plus one media occurrence. The original file is the
primary/original representation and owns declared MD5, byte size, extension/MIME, and dimensions.
Sample and preview are named variants with their own dimensions and URLs but do not inherit exact
original claims. Store provider-returned URLs privately as occurrence/variant metadata.

Map `flags.deleted` to deleted post availability. A null original URL on a non-deleted post makes
that representation unavailable without changing post availability to deleted. Null sample or
preview URLs simply omit or exclude those variants. MD5-based static URL construction is forbidden
because null can reflect provider policy or processing state rather than a derivable location.

Persist known tag categories through the neutral category vocabulary where it is lossless. Keep
the provider spelling/category and raw response so species, lore, contributor, invalid, and future
categories are not collapsed silently; the schema audit decides whether the current tag vocabulary
needs an additive extension. Preserve sources, parent/child links, pool IDs, rating, score, counts,
uploader role, timestamps, and flags through existing neutral facts or the smallest new neutral
observation contracts.

Alternatives rejected:

- Treating every null URL as deletion loses valid provider state.
- Applying original MD5/size to samples creates false verification mismatches.
- Flattening all unfamiliar tags to general discards provider meaning.

### 4. Use ID-keyset continuations and immutable rendered target material

Post listing starts without a page cursor and continues toward older IDs with `page=b<ID>` derived
from the committed boundary. Continuations include provider, operation, canonical attribution
target, direction, last ID, adapter version, and continuation version. They are opaque in public
output and contain no credentials or rendered source query.

The adapter requests at most 320 records and the shared executor admits the request only if request,
page, record, and elapsed-time budgets permit it. A page's raw response, normalized records,
expansion associations when applicable, and next continuation commit atomically. Numeric pages are
not used for durable enumeration.

Alternatives rejected:

- Numeric pages can shift as posts are added or removed and fail beyond the provider's page window.
- Reusing only the last row offset without target/version identity makes resumes unsafe.

### 5. Model tags, aliases, artist records, and uploaders as separate evidence

Use stable e621 tag IDs as provider attribution identities where available. Retain tag name,
category, post count, lock state, and observation time. Retain alias ID, antecedent, consequent,
status, counts, timestamps, and raw provenance as a directed provider alias observation. Only
active/approved alias state is eligible for the declared alias lookup strategy; ambiguous or stale
state remains a weak lead or exclusion.

Artist records remain attribution metadata keyed by their provider artist ID, with name, other
names, domains, URLs, lock state, and linked-user ID retained as facts. A linked user and an uploader
are not external accounts. External URLs are passed through existing link recognition and review
flows; only a recognized stable account reference may create an account candidate.

Post normalization records artist-category tags as attribution and uploader ID/name only in the
uploader role. It does not assert that every artist tag has an artist-record object or that the
uploader authored the work.

Alternatives rejected:

- Using the tag text alone as a stable cross-platform account violates the identity model.
- Resolving aliases without status/provenance can silently redirect historical or pending names.

### 6. Extend lookup through a provider-neutral planning boundary

Refactor the current Danbooru-specific lookup planner input just enough to accept a provider lookup
configuration/protocol with provider key, versions, declared strategies, request renderer, and
normalizer. Preserve the public planning/service/CLI contracts and existing Danbooru/AIBooru
behavior.

For e621, source URL and external post ID render bounded post tag queries; declared/verified MD5
uses the provider's `md5:` search; exact artist lookup consults exact tag/artist metadata; alias
lookup consults retained or bounded alias results. Arbitrary fuzzy artist text is not declared in
this change. Results reuse the existing candidate/evidence ledger and never auto-confirm.

Alternatives rejected:

- Adding e621 conditionals around the hardcoded Danbooru provider string would deepen the current
  provider leak and produce incorrect plan identities.
- Treating artist search results as accounts bypasses explicit review.

### 7. Extend library expansion with stable e621 attribution capability

Register an e621 attribution enumeration capability using the exact canonical artist tag privately
rendered by the adapter. Planning remains read-only and resolves only a stable retained attribution
entity. Expansion execution composes the existing metadata sync and origin association; it adds no
new checkpoint or result store.

An offline estimate uses a retained current exact canonical artist-tag `post_count` only when its
tag ID/category and alias state match the selected attribution unambiguously. The estimate carries
observation time and source and is not an execution guarantee. Multi-tag/filtered counts and absent
or ambiguous tag state remain unknown. No implicit count request or listing page is used as a count.

Alternatives rejected:

- `X-Total` and undocumented count routes are not provider contracts.
- Using the first page length as a total produces false estimates.

### 8. Add a dedicated e621 acquisition policy based on returned URLs

Register a versioned e621 `MediaRequestPolicy` for original, sample, and preview variants. The
policy accepts HTTPS only, validates known `staticN.e621.net` media hosts using a deliberately
bounded hostname rule rather than arbitrary subdomains, supplies the descriptive User-Agent and
required referer if verified, and validates each redirect before following it. Host acceptance and
redirect behavior are tested with retained response shapes and bounded live metadata discovery;
media bytes remain mocked in default tests.

Original acquisition compares verified output to declared original MD5, size, MIME/extension, and
dimensions. Sample/preview acquisition stores verified representation facts without applying
original claims. The existing staging, quarantine, CAS, idempotency, and inspection contracts are
unchanged.

Alternatives rejected:

- Accepting every `*.e621.net` host is broader than necessary.
- Deriving static hosts or paths from MD5 when the returned URL is null defeats availability policy.

### 9. Audit the neutral schema before selecting a migration

First map every required e621 fact to current records and tables. Reuse existing post,
post-participant, tag, post-tag observation, attribution, URL/name snapshot, post relationship,
media occurrence/variant, raw observation, and declared fact contracts when they retain identity,
time, and provenance losslessly.

Add a numbered migration only for demonstrated gaps, likely versioned tag-alias observations,
additional neutral tag categories/provider flags, or attribution-to-tag identity. Any migration is
additive, uses closed vocabularies and foreign keys, preserves prior IDs, and includes fresh,
upgrade, failed-migration rollback, doctor, and foreign-key tests. Provider-specific JSON columns or
parallel e621-only post/media tables are forbidden; raw JSON remains in raw observations.

### 10. Treat fixtures as the executable provider contract

Commit redacted fixtures for normal image, video or animation if observed, deleted post, nondeleted
null-media post, unknown ID, tag, alias, artist, first listing page, continuation page, malformed
shape, authentication, authorization, rate limit, and transient failure. Fixtures retain structural
fields and stable synthetic IDs while removing credentials, descriptions, sensitive source text,
and unnecessary uploader names. Media URLs may be synthetic but must exercise the verified host and
path shapes.

Tests inject transport and assert exact request count, method, host, path, non-secret parameters,
headers by name, pacing, continuation, raw retention, normalization, and zero media requests.
Disabled live tests make at most the documented small number of metadata requests and never open
returned media URLs.

## Risks / Trade-offs

- **[e621 changes fields or rate policy]** → Version configuration/schema/fixtures, retain raw
  responses, fail malformed rather than guessing, and keep pacing stricter than the hard ceiling.
- **[Null media URL is misinterpreted]** → Derive deletion only from explicit flags/status and model
  each representation's availability independently.
- **[Dynamic tag categories exceed the neutral vocabulary]** → Preserve raw category names and use
  an additive neutral migration only after the schema audit.
- **[Alias or artist records are mistaken for accounts]** → Keep typed attribution/alias entities
  and require stable recognized account URLs plus review for identity.
- **[Provider media hosts vary]** → Base policy on returned URLs and fixture/live metadata evidence,
  version the allowlist, and fail closed on unknown hosts.
- **[Lookup refactor regresses Danbooru/AIBooru]** → Characterize existing plans, request identities,
  fixtures, result persistence, and resume behavior before extracting the provider boundary.
- **[High-volume tag histories tempt bulk crawling]** → Keep per-run budgets and keyset resume;
  database exports and background enumeration remain separate future work.

## Migration Plan

1. Audit existing schema and provider-generic lookup/expansion/acquisition seams; add characterization
   tests before refactoring shared boundaries.
2. Commit redacted e621 fixtures and versioned configuration/contracts, then implement metadata-only
   fetch and normalization with injected transports.
3. Add the smallest additive migration, records, and writer/query changes only if the audit proves
   required facts cannot be represented.
4. Enable standalone sync and resume, then candidate lookup and artist-library expansion through
   the proven provider boundary.
5. Add the e621 media request policy and verify selected variants through the existing acquisition
   pipeline without changing CAS semantics.
6. Add CLI/docs/live-test opt-in, run compatibility and privacy gates, and validate/review the full
   change. Rollback application code before applying any new migration; after migration, older
   binaries reject the newer schema while additive data remains intact.
