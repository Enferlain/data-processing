# Stage 2 Design: Index-Backed Discovery and Search Optimization

Status: design (2026-11-08) — implementation follows in slices.
Owner: bead `data-processing-an1`; first slice: OpenSpec change
`add-local-search-indexes`. Stage 1 (policy/freshness/queue) is delivered and
archived (`2026-11-08-add-discovery-search-policy`).

## 0. Problem and principle

Per-item discovery today treats every subject as new: local catalog steps,
then live provider queries. At corpus scale that recrawls providers for
knowledge we (or a public dataset) already hold. The fix is not a mirrored
copy of the internet inside the primary catalog — it is **search
infrastructure that is disposable, refreshable, and source-specific**:

```text
PRIMARY CATALOG (truth: observed/reviewed, provenance, evidence)
        │ queries
        ▼
LOCAL SEARCH INDEXES (one per provider; lookup.sqlite + state)
        │ candidate hits (leads, not facts)
        ▼
normal fetch/reconciliation pipeline (existing provenance machinery)
```

An index hit means "provider X probably has post Y at snapshot S". Only the
existing fetch path creates catalog facts.

## 1. What existing local knowledge already acts as an index (tier 0)

The catalog itself is already the first index; discovery already queries it
(stage-1 local steps). Inventory, verified 2026-11-08:

| Knowledge | Table(s) | Indexed by | Discovery use today |
|---|---|---|---|
| verified/declared md5+sha256 | `asset_fingerprints` | `(fingerprint_kind, fingerprint_value)` | `local_md5` |
| perceptual hash | `asset_fingerprints` (`phash`) | value index (equality only) | none yet — tier-2 candidate |
| canonical post URLs | `posts.canonical_url` | index exists | `local_platform_identity` |
| source URLs | `external_links` + `post_external_references` | canonical_url index | `local_source_url` |
| cross-platform ids | `platform_references` (stable_id/handle/slug) | indexed | via materials (`external_post_id`) |
| artist identity | `accounts`, `account_snapshots`, attribution evidence | various | artist materials (name-based) |
| retained raw observations | `raw_payloads`/`raw_observations` | per-run | reprocess; future artist-identifier mining |

Consequence: tier 0 needs no new machinery. The gap is everything below.

## 2. External index targets (tiers 1–2)

**One database per provider** — different refresh mechanisms, schemas, update
rates, snapshot ages, failure modes — all exposing one logical interface:

```text
indexes/<provider>/lookup.sqlite     OUR derived projection (format lookup-v1)
indexes/<provider>/state.json        snapshot identity + watermarks
downloads/<provider>/…               raw provider artifacts (kept; rebuild source)
```

Raw artifacts are **retained separately from the derived projection**: the
importer records the artifact's path and digest in `index_meta` and never
modifies or deletes it; the projection is always rebuildable from the
artifact, and the artifact is never rebuilt from the projection. A schema
change therefore never makes our projection the only copy of anything.

### lookup-v1 projection schema (ours)

```sql
CREATE TABLE posts (
    post_id INTEGER PRIMARY KEY,
    md5 TEXT, source TEXT, parent_id INTEGER,
    file_ext TEXT, width INTEGER, height INTEGER,
    created_at TEXT, updated_at TEXT, is_deleted INTEGER,
    origin TEXT NOT NULL,            -- 'export' | 'api'
    first_seen_at TEXT NOT NULL, last_confirmed_at TEXT
);
CREATE INDEX idx_posts_md5 ON posts(md5);
CREATE TABLE post_sources (post_id INTEGER, normalized_url TEXT,
    PRIMARY KEY (post_id, normalized_url)) WITHOUT ROWID;
CREATE INDEX idx_sources_url ON post_sources(normalized_url);
CREATE TABLE post_artists (post_id INTEGER, artist_tag TEXT,
    PRIMARY KEY (post_id, artist_tag)) WITHOUT ROWID;
CREATE INDEX idx_artists_tag ON post_artists(artist_tag);
CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT);
-- keys: format, provider, snapshot_revision, source_digest, built_at,
--       builder_version, record_count, max_post_id, max_updated_at
```

SQLite is the right engine for the hot path (`WHERE md5 = ?`,
`WHERE normalized_url = ?`, `WHERE post_id = ?` — B-tree point lookups);
Parquet/DuckDB stay bulk/rebuild tools, not lookup targets.

### Source availability (verified 2026-11-08)

| Provider | Bulk source | Strategy |
|---|---|---|
| e621/e926 | official daily DB exports, gzipped CSV + SHA-256, JSON listing at `/db_exports.json`; posts 1.86 GB, artists 7.3 MB | **full rebuild from export** (daily full corpus ⇒ no incremental needed); revision = export checksum/date |
| danbooru | public metadata datasets (e.g. `Jannchie/danbooru_metadata`, HF, MIT) + own API | build our projection from a metadata snapshot; incremental by id/update watermark later |
| gelbooru | none public; API has `md5:`, `source:`, `cid` change-id | **encountered-cache + teach-on-result**; optional `cid` watermark refresh with overlapping windows (multiple records share a `cid`; never assume `>` is once-only) |
| aibooru | API mirror only | mirror via teach-on-result; bounded listing sync later |
| sankaku | none public; search API supports `md5:`, `id_range:` | encountered-cache + teach-on-result; optional bounded `id_range` sync |
| pixiv | no public metadata dump | artist-scoped only, via existing expansion machinery |

### Registration and discovery integration (reuses stage 1 verbatim)

- New migration: `search_index_registrations` (target name, provider
  platform key for fetch routing, index_kind/format, private path, snapshot
  revision, registered_at/last_refreshed_at). Path storage follows the
  `managed_roots.private_path` precedent.
- **Identity is the target name, never the path**: the registration (and
  every ledger attempt, policy reference, and report row) keys on the
  registered target name; the path is mutable plumbing. Moving or renaming
  the projection file and updating the registration preserves the target's
  identity, search history, and freshness state.
- Index targets appear in the planner as `source_kind='index'`, one decision
  row per (index, method) — included/excluded by the same `--include-source`
  policy, skipped fresh with the attempt named, explainable in `--dry-run`
  and `--search-state` exactly like any other target.
- Methods for slice 1: `verified_md5`/`declared_md5` → md5 column;
  `source_post_url` → normalized_url; `external_post_id` → post_id;
  artist-name lookups via `post_artists`/artist export. `fetch_post`
  follow-ups fetch by provider post id through the existing wave machinery.
- **Freshness**: the attempt's strategy version becomes
  `lookup-v1.<revision>.g<overlay_generation>` where `<revision>` is the base
  import identity (artifact digest + builder version + scope: `full` when
  the artifact was consumed to EOF, else the bounded prefix size — a bounded
  shakeout and a full import of the same artifact are different revisions)
  and the overlay generation counts teach mutations since the build (bumped
  only when a teach batch actually changes content). Refresh, expanded
  import, or taught content each change the version, so affected subjects'
  index searches replan — a remote result teaching the exact md5 of a prior
  miss invalidates that miss. This is the "searched e621 snapshot 2026-11-08,
  not just e621" guarantee, extended to mutable taught content.
- **Execution is offline**: index steps are local reads; they run without
  `--live`, consume no request budget, and order before provider steps
  (planner emits tier 0 → tier 1 → providers). Local-first is structural,
  not a flag.
- **Independence**: an index hit never satisfies the live-provider key or
  vice versa; both stay recorded.

### Hit semantics and the fetch bridge

Index rows never enter `posts`/`observations`. An index step's hits land in a
small `discovery_index_hits` side table (session, provider, post id, md5,
sources) and are reported as leads. When the session is live-authorized, the
existing wave-A planner unions these hits with lookup-run hits and plans
`fetch_post` steps — the normal fetch pipeline then writes real records with
real provenance. Zero-result index searches record their snapshot and scope
like every other bounded search.

### Teaching: one post-commit boundary, every entry point (hard requirement)

Teaching lives at the **normalized-post persistence boundary**, not in any
one caller: every path that persists a provider post — `catalog fetch`,
direct metadata sync, candidate lookup, and discovery (whose provider steps
run through the same services) — writes through `NormalizedPageWriter`
(`remote_sync/persistence.py`); that is the single hook point. When a page
commit lands, the writer's post-commit hook upserts the post identity
(provider post id, md5, canonical URL, provider source URLs, artist tags)
into that provider's registered `lookup.sqlite` with `origin='api',
last_confirmed_at=now` (reprocess passes through the same writer and
re-confirms for free). Each batch is one projection transaction — whole or
rolled back, never partial — bumps the overlay generation only when content
actually changed, and records a durable `teach_log` row for inspection.
Failure containment is structural: the hook runs after the page's catalog
transaction commits, wraps everything in try/except, and records at most a
bounded diagnostic note — an index write can never fail, roll back, or delay
catalog success. With no registered index the hook is a no-op.

### Maintenance is a separate lifecycle

Discovery only reads. Maintenance commands own writes:

- `catalog index register/list` — bind a projection to a provider target.
- `catalog index import --provider e621 --artifact posts.csv.gz` — verify
  SHA-256, stream-build the projection, transactional swap, bump revision.
- `catalog index import --provider e621 --download` — fetch today's export
  from the public db_exports listing (checksum-verified, identifying
  User-Agent, artifact retained under downloads/); a matching existing
  artifact is reused. For e621 this **is** the refresh: daily full exports
  mean no separate watermark machinery.
- `catalog index refresh` (later slice, non-export providers) — danbooru:
  watermark increment; gelbooru: `cid` window with overlap + dedup; sankaku:
  bounded `id_range`. State/watermarks live in `state.json` + `index_meta`,
  never in the primary catalog beyond registration.

## 3. Artist-identifier search (investigation)

Today's artist strategies are name-based (`artist_exact_name`/`alias`/`text`).
Identifier-based search uses the artist's *stable account identity* on one
platform to find their entries elsewhere — much stronger than names.

Catalog material (already present): `accounts.native_account_id` + platform,
`account_snapshots` handles/display names, `platform_references` with
`identifier_kind` (stable_id/handle/slug), attribution evidence.

Provider surfaces (verified): danbooru `/artists.json` supports
`search[url]=…` attributes and artist records carry URLs + other names, so a
known pixiv/twitter account URL resolves to a danbooru artist entry and its
tag; e621 (same software family) exposes artist URL search equivalently;
gelbooru declares no artist endpoint (already excluded in planning); sankaku
supports artist tag search.

Proposed method `artist_identifier` (new `LookupStrategy` value, bumps
`LOOKUP_STRATEGY_VERSION` deliberately): resolve the subject's known account
URL/id → provider artist entry (URL search) → artist tag → post search.
Classed ACTIVE under stage-1 policy (derived query), so it stays excluded
until `--search-mode active` or a search term implies it. Slice: after index
read path — the artist exports (e621 7.3 MB, danbooru artists in metadata
datasets) make identifier→tag resolution a *local* index lookup too.

## 4. Reverse-image / content-based search (investigation)

Two different problems; keep them separate:

**Local tier-2 (own corpus):** we already persist `phash` per asset
(`asset_fingerprints`, value-indexed). Equality lookup is trivial but hamming
similarity needs a scan or a purpose-built structure. Danbooru's open-source
IQDB stores fingerprints in SQLite with add/remove/query — a compatible
local index could make "visually similar within my corpus" a `lookup-v1`
sibling format (`iqdb-v1`). Constraint from
`docs/plans/matching-crop-resistant-evaluation.md`: whole-image hashes
(incl. phash) are crop-blind and segmentation-based region matching was
eliminated — fingerprint indexes help for re-encodes/resizes/transcodes, not
crops. No implementation until a demonstrated query needs it.

**Remote reverse-image (tier 4):** SauceNAO (key-based JSON API,
`output_type=2`, database-index selection covering pixiv/danbooru/e621
subsets; strict rate limits — recommended API key; verify current quotas at
implementation) and danbooru's own `iqdb_queries` endpoint. These are
*search-service targets*, not provider adapters: method `reverse_image`,
classed ACTIVE, network-cost metered like provider requests, and — because
they **upload operator images to a third party** — gated behind explicit
method enablement in the policy, never implied by `--live` alone. Findings
return as leads into the same fetch bridge.

## 5. Tier order and scaling win

```text
T0 primary catalog → T1 provider metadata indexes (md5/url/id/artist)
→ T2 fingerprint indexes (phash/iqdb) → T3 semantic (embeddings/OCR; far)
→ T4 remote search (provider APIs, reverse-image services)
```

Typical resolution path: md5 → T1 hit → single provider fetch. Fallbacks
walk down the tiers; a tier answering makes lower tiers unnecessary *for that
subject/method/evidence* — exactly what the stage-1 freshness key expresses.

## 6. Slice plan

1. **add-local-search-indexes** (first change): registration migration,
   `lookup-v1` projection + e621 export importer, index read path in
   planning/execution/ledger (`--dry-run`, `--search-state` show targets),
   `discovery_index_hits` + fetch bridge, teach-on-result at the shared
   normalized-post boundary, `catalog index register/list/import`,
   docs/tests. **e621 alone is the complete first vertical slice** — its
   daily exports are verified and cover the whole architecture; the danbooru
   snapshot importer is a follow-up task inside the same change, started
   only once the operator supplies a concrete artifact and its layout is
   verified (unresolved format must not expand the first slice).
2. Refresh lifecycle: `index refresh` per-provider strategies + watermarks.
3. `artist_identifier` method (provider artist-URL search + local artist
   index resolution).
4. Tier-2/4: local iqdb-format index; SauceNAO/danbooru-iqdb reverse-image
   target behind explicit opt-in.

Deferred explicitly: semantic indexes, whole-provider mirrors beyond exports,
any copying of external datasets into the primary catalog.
