## Context

See `proposal.md` for motivation and the two capability specs for observable behavior. The current
catalog stores account website/profile fields in temporal snapshots, post text and canonical URLs in
stable records, X entity/card data in retained raw JSON, and provider facts such as quote/reply in
`post_relations`. It has no durable external-link observations, cross-platform object references,
identity groupings, match candidates, evidence ledger, or review history.

The imported xarchive shape already prefers expanded account website URLs and preserves expanded
post entity links. Direct Pixiv and Danbooru-family resource URLs can therefore yield useful stable
references offline. Shorteners, link hubs, and personal sites cannot be resolved safely without a
separate network workflow.

Local references and the public examples below confirm several constraints: Pixiv numeric user and
artwork IDs are stable while handles are secondary; Pixiv works can contain several page occurrences;
Danbooru-family native IDs must be namespaced by instance hostname; booru artist records, uploaders,
posts, media assets, and artist tags are different concepts; Mastodon-compatible status IDs are also
instance-scoped; and a booru MD5 or source URL is evidence rather than proof of creative ownership.

## Goals / Non-Goals

**Goals:**

- Reprocess existing catalogs offline without changing source imports or raw payloads.
- Preserve every link occurrence and its JSON path or normalized-field context even when several
  occurrences canonicalize to one target.
- Keep external platform references useful before a target account or post has been fetched into the
  catalog.
- Enforce typed account and post candidates with independently reviewable evidence.
- Make every derived record idempotent, versioned, and auditable.
- Leave explicit extension points for later media and work-version evidence without pretending that
  this change implements image matching.

**Non-Goals:**

- HTTP redirects, link-hub traversal, arbitrary site scraping, or live platform API adapters.
- Account crawling, pagination jobs, credentials, rate limiting, or media downloading.
- Exact/perceptual image comparison, automatic transformation classification, work/work-version
  entities, or highest-quality/original selection.
- Automatic identity merges, transitive confirmation, or creator inference from names, uploaders,
  artist tags, links, hashes, or similarity scores.
- Replacing provider-observed `post_relations` with reviewed cross-platform hypotheses.

## Decisions

### 1. Store link targets separately from link observations

Add a migration whose link layer contains:

- `discovery_runs`: start/finish state, extractor/recognizer/scoring versions, counts, and bounded
  diagnostics for one offline derivation pass.
- `external_links`: one deterministic canonical URL identity plus resolution state and the
  canonicalization version.
- `link_observations`: original URL, source subject type/id, account snapshot or post/raw observation,
  source context and JSON path, observed time, discovery run, and a stable occurrence digest.
- `platform_references`: recognized platform/instance, object kind, native identifier, canonical
  target URL, recognizer/version, and optional later resolution to a local account or post.

The same canonical link may have many observations. Idempotency keys include source identity and
context, so a profile website and a post entity pointing to the same URL remain separate provenance.
Original URLs are never overwritten by canonicalization.

Alternative considered: store one link row directly on each account/post. Rejected because it loses
history, raw location, repeated contexts, unresolved targets, and extraction-version provenance.

### 2. Use pure versioned extractors and a recognizer registry

Discovery is a pure pipeline over catalog rows and decoded retained JSON:

```text
source record -> URL occurrence -> conservative canonical URL
              -> platform recognizer -> optional stable reference
              -> typed candidate/evidence generation
```

V1 extractors cover normalized account website/profile/bio fields and supported X/xarchive post text,
entity, card, and quoted/source locations. Recognizers cover direct X account/post, Pixiv user/artwork,
Mastodon-compatible account/status, Danbooru `/posts/<id>` and `/post/show/<id>`, Gelbooru query-style
post, e621 legacy/current post, and configured booru artist/media-asset patterns. Pixiv locale/legacy
route aliases may canonicalize to their stable numeric target. Booru and Mastodon-compatible
references retain instance hostname; a service family or display handle alone is not a namespace.

Canonicalization removes only explicitly recognized non-semantic components. Original query and
fragment values remain on observations; a recognizer may omit them from a direct-resource canonical
target only when its versioned rule establishes that they do not change identity. Unknown, malformed,
shortened, or link-hub targets receive bounded states rather than synthetic IDs.

Alternative considered: use live redirects during extraction. Rejected because it would make an
otherwise deterministic local derivation dependent on network safety, availability, and rate limits.

### 3. Keep provider object kinds distinct

`platform_references.object_kind` uses a small validated registry including `account`, `post`,
`artist`, and `media_asset`. Pixiv artwork references normalize as posts; multi-page files remain
future media occurrences beneath that post. A booru artist record or tag is not normalized as an
uploader account, and an external source URL is not normalized as a booru post.

When an adapter later imports the referenced object, the reference may resolve to its local stable
account/post row without changing the original link observation or candidate identity.

Alternative considered: represent every remote URL as an account or post placeholder. Rejected
because it fabricates types and makes later adapter reconciliation unsafe.

### 4. Use separate FK-safe account and post candidate tables

Add `account_match_candidates` and `post_match_candidates`, each with type-appropriate local source
foreign keys and a target that is either a matching local object or a compatible external platform
reference. Check constraints require exactly one valid target representation. Stable candidate keys
canonicalize symmetric local pairs where appropriate while preserving direction for official-link,
source, repost, and derivative claims.

Account relation families initially include same-identity and officially-linked hypotheses. Post
families initially include `sourced_from`, `same_work`, `repost_of`, `variant_of`, `derived_from`, and
`unresolved`. The candidate subject is the locally observed post and every directed term reads from
that subject toward its target; for example, an X post citing a Pixiv artwork is `sourced_from` the
Pixiv target. `same_work` is symmetric and receives a canonical endpoint ordering. The vocabulary is
deliberately small and versioned. Repeatable post-candidate characteristics can later record facts
such as resized plus re-encoded, or ordered progression labels, without forcing one exclusive
transformation enum. In this change characteristics are representational/manual data only: no bytes
are fetched and no hashes, perceptual comparisons, or automatic variation labels are produced.

Canonical self-links remain valid link observations but candidate generation rejects a candidate
whose resolved account or post endpoints are the same object. This prevents normal X profile and
post canonical URLs from generating meaningless self matches.

Existing `post_relations` remains the ledger for provider-observed quote/reply/repost facts. Reviewed
cross-platform candidates do not overload it; a confirmed candidate is itself the durable reviewed
relationship together with its latest state and complete decision history.

Alternative considered: one polymorphic candidate table. Rejected because SQLite could not enforce
account/post endpoint integrity without extensive triggers and kind-dependent nullable columns.

### 5. Share immutable evidence but use typed joins and decisions

`match_evidence` stores a stable evidence digest, stance, evidence kind, direction, strength,
detector/version, observation/reference provenance, timestamp, and structured explanation components.
Typed join tables attach an evidence item to account or post candidates. One observed URL can produce
separate items when it supports different claims.

Each candidate stores a query-friendly current state and current deterministic score snapshot.
Append-only typed decision tables store state transitions, reviewed evidence generation, timestamp,
and optional user note. The score is only a review ordering aid: confirmation always requires a
decision event, and later scoring versions never overwrite decision history.

Alternative considered: one confidence column on a relationship. Rejected because it hides why a
claim exists, confuses algorithm ranking with human judgment, and cannot preserve reconsideration.

### 6. Materialize identity membership only from explicit confirmation

Add `identities` and provenance-bearing `identity_accounts`. Confirming a same-identity account
candidate creates or extends a grouping only through the recorded decision. When its target is a
recognized account reference with a stable native ID but no local row, confirmation first creates a
metadata-empty discovered account, resolves the reference to it, and then adds membership; it never
fabricates a handle, name, profile fields, or fetched state. References without a stable account ID
cannot form an account candidate. Confirmation does not rewrite snapshots, posts, participants, or
raw observations, and it does not transitively confirm every pair in the group. Conflicts are
reported for review instead of silently merging two existing identity groups.

Post confirmation changes only the candidate's reviewed state. Work grouping is deferred until the
image/work-model change because creating a work for every linked post pair would prematurely fix the
catalog's semantic granularity.

Alternative considered: union-find account merges. Rejected because they are difficult to reverse,
make transitive assumptions, and erase the evidence boundary between platform accounts and identity.

### 7. Add a narrow offline CLI surface

Use these command families, with final option spelling settled during implementation:

```text
catalog discover-links CATALOG [--json]
catalog links CATALOG [subject/platform/kind/state filters] [--json]
catalog matches CATALOG [--kind account|post] [--state ...] [--json]
catalog match-show CATALOG MATCH_REF [--json]
catalog match-review CATALOG MATCH_REF --decision confirm|reject|pending [--note ...] [--json]
```

Discovery output reports run/version/count data. Listing output exposes normalized evidence summaries
but not entire retained raw payloads. Errors reduce private catalog/source paths to safe labels.

Alternative considered: fold discovery into import. Rejected because algorithm upgrades must be
rerunnable without reimporting private exports or creating new user observations.

### 8. Keep public reference examples as metadata-only fixtures

The following public cases were checked on 2026-08-06 through page/API metadata only. No media files
were opened or downloaded. Fixture copies retain only public identifiers, source URLs, hashes,
dimensions, relationship metadata, and user-supplied expected labels.

- **Case 1 — Pixiv/X/Danbooru/Gelbooru:** Pixiv artwork `133416234` belongs to numeric user
  `27631291` and its description links the X handle `yyqw7151`. X post `1950567258528547071`,
  Danbooru post `9714844`, and Gelbooru post `12370900` describe a 1150x1750 JPEG with MD5
  `fef8d5889c2fe425dd50cfade909cec9`. Danbooru marks it as a child of Pixiv-backed post `9729919`,
  a 1150x1750 PNG with a different MD5. This supports exact cross-booru asset evidence, strong
  account-link evidence, and same-work/technical-variant evidence without proving which upload time
  identifies the creative original.
- **Case 2 — X/Baraag/Danbooru/Gelbooru/e621:** Danbooru post `8996458` and Gelbooru post `11605534`
  share MD5 `7cd330523b8e34b97c40e02c7e87d98c`, dimensions 1153x1333, and a Baraag source. e621 post
  `5433323` has the same dimensions and PNG format but MD5 `47f89865202da62a62467bbcec220818`
  and cites X post `1900654502380007860`; both source posts were unavailable to anonymous metadata
  lookup at check time. This is a same-work candidate with an unresolved transformation, not an
  exact match, and demonstrates why durable source metadata must outlive remote availability.
- **Case 3 — X/Danbooru/Gelbooru variations:** X post `1837662117949800671`, Danbooru post `8186581`,
  and Gelbooru post `10720246` share MD5 `072b69605a05873a2443626b7600ed69` and dimensions
  1401x2048. Gelbooru posts `10791439` and `10791440` are distinct 1471x2151 PNG assets with different
  MD5 values and blank source fields. The user identifies three related variations: a text/no-text
  pair and a third content variation. That assertion remains user-supplied evidence until later
  byte/perceptual analysis can refine the relationships.

These cases are regression inputs, not live integration tests. Tests never depend on the sites being
available and never fetch their media URLs.

## Risks / Trade-offs

- [Raw provider schemas evolve] -> Keep extractors source/version specific, retain JSON paths and raw
  payloads, and emit bounded per-record diagnostics instead of treating missing fields as empty data.
- [URL canonicalization can collapse distinct resources] -> Use conservative allowlisted rules,
  version them, preserve original observations, and regression-test every supported pattern.
- [One URL can support different claims] -> Store immutable evidence per claim and never derive
  account ownership from post-source evidence.
- [Canonical profile/post URLs create self references] -> Preserve their observations for provenance
  but reject self candidates after endpoint resolution.
- [External references may later resolve differently] -> Keep reference identity separate from the
  optional local-object link and retain recognizer/version provenance.
- [Identity confirmation can conflict with earlier groupings] -> Refuse silent group unions and
  require an explicit follow-up decision.
- [A relation vocabulary can become an accidental ontology project] -> Start with broad families,
  retain unknown/unresolved, allow repeatable characteristics, and add terms only from real examples.
- [Large raw catalogs make rescans expensive] -> Index source/object/version digests and skip
  unchanged observations while preserving run reconciliation counts.

## Migration Plan

1. Add the numbered migration and validate creation, upgrade, rollback-on-failure, foreign keys,
   doctor output, and unchanged existing catalog counts.
2. Add pure URL extraction/canonicalization/recognition records and synthetic X/xarchive fixtures.
3. Add offline discovery-run persistence, reconciliation, rerun idempotency, and link queries.
4. Add typed candidates, shared evidence, versioned scoring, and candidate inspection.
5. Add append-only review decisions and explicit identity membership materialization.
6. Add the CLI/documentation and run the feature against a user-selected catalog copy plus redacted
   public examples, never committing private archive data.

Rollback is to stop using the new commands and restore a catalog backup created before migration.
The migration does not rewrite or delete accounts, snapshots, posts, observations, media, assets, or
raw payloads, and source exports remain untouched.

## Open Questions

- Which additional direct URL aliases should be admitted after testing the first 3-5 public artist
  examples beyond the Pixiv, X/Twitter, Mastodon-compatible, Danbooru, Gelbooru, and e621 forms now
  represented? Adding aliases does not change the data model or offline boundary.
- Which broad post-relation characteristics recur often enough in those examples to deserve
  normalized terms rather than preserved source labels?
