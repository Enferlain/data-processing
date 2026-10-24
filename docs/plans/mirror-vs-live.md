# Local mirror vs live API: provider metadata at scale

Status: decision recorded (2026-10-24; Bead `data-processing-6cu`)
Related: [provenance kernel plan](provenance-kernel.md), [metadata audit](metadata-audit.md),
[non-media consumer spike](non-media-consumer-spike.md), the bounded-candidate-lookup and
artist-library-expansion specs.

Target-database metadata reaches tens to hundreds of millions of rows. Whether the catalog keeps
local copies, fetches against APIs, or both, has different costs in storage, latency, API volume,
and provider etiquette — and the choice shapes every audit-driven capability (hash and source
matching both need queryable provider metadata). This document sizes the problem, splits the
queries, evaluates the options, and records the decision.

## Sizing

**Measured** (real catalog, schema 15, partial corpus, metadata-only — no assets downloaded):
1,669 bytes per retained post across the five hot tables — raw payloads 1,035 B (62%),
media occurrences 178 B, posts 231 B, platform references 124 B, raw observations 101 B —
plus ~1.08 occurrences and ~1.0 platform reference per post — 5.05 rows across the five
measured hot tables per retained post. Tag and post-tag multiplicity is
under-measured in this corpus (partial library) and index pages are excluded (the five
tables' autoindexes and secondary indexes add another ~394 B/post), so the per-post figure is
a floor.

**Provider scale** (live counts where public, 2026-10-24):

| Provider | Posts | Full metadata mirror at ~1.7 KB/post | Notes |
| --- | --- | --- | --- |
| Danbooru | 12,386,307 (live `counts` endpoint) | ≈ 21 GB, ~62 M rows over the five measured hot tables | paged API only (limit ≤ 200); full sweep ≈ 62 k requests |
| Gelbooru | order 10⁷ (not verifiable anonymously; dapi requires credentials) | same order as danbooru | dapi only, credentialed |
| e621 | single-digit millions (no public counts endpoint) | ≈ 3–16 GB | paged API |
| Pixiv | two orders larger, but the repo syncs account-local libraries, not the corpus | n/a for corpus mirroring | account-scoped by design |

## Which queries must be local, and which can stay live

| Query class | Home | Why |
| --- | --- | --- |
| Reprocessing, projections, as-of reconstruction | **local** | reads retained raw reports by definition (the evidence layer) |
| Dedup sweeps, hash indexes over acquired assets | **local** | offline joins over the *retained* corpus only — assets in custody are finite |
| Cross-source matching over retained works | **local** | offline joins; the candidate machinery then feeds bounded live lookups |
| Point lookups by source URL / hash / id against the provider corpus | **live, bounded** | the bounded-candidate-lookup contract: typed outcomes, budgets, no corpus copy |
| Growing a library (all posts of an artist) | **live, bounded** | artist-library-expansion enumeration; result retained locally as evidence |

The decisive observation: **the kernel only needs provider metadata for posts it retained or is
actively comparing against.** The retained corpus is local by construction — provenance demands
it — so "local vs live" is really about whether to mirror provider metadata *beyond* what the
evidence layer retained.

## Options evaluated

1. **No mirror beyond retained evidence; live lookups only.** Point queries stay bounded-live;
   offline joins cover the retained corpus. Cost: provider-scale offline questions ("does any
   provider post have this hash?") are impossible — but no current capability asks them.
   Etiquette: minimal. Storage: scales with the library, not the provider.
2. **Selective mirror (per-artist work corpora).** The current architecture: library expansion
   enumerates an artist's posts and retains them as evidence. Cost scales with library size;
   every retained row carries provenance. This is not a "mirror" in the dump sense — it is
   evidence acquisition.
3. **Full metadata mirror with periodic refresh.** ~21 GB for danbooru alone (~40 M rows), plus
   tag/post-tag overhead not yet in the floor estimate; a full refresh sweep is ~62 k requests
   (at the 200-post page ceiling), and periodic refresh re-fetches churn. SQLite handles the size
   offline, but the write path and single-writer contention degrade, and every retained row
   obligates the audit tier (immutable raw payloads) with no provenance story for rows nobody
   asked for. Benefit: provider-wide offline queries — which nothing currently needs.
4. **External bulk datasets** (community exports of danbooru-class sites). The import path exists
   (`x-seed-import` precedent: bulk sources land through provenance-carrying import runs), so
   this remains available without new machinery. No blessed dump source exists today; adopting
   one is a source decision, not a schema change.

## Decision

**Stay on the selective architecture (option 2 inside option 1's discipline):**

- Local = the retained evidence layer plus its projections — metadata for posts the catalog has a
  provenance reason to hold. No full-provider mirror now.
- Live = bounded point lookups (candidate lookup) and bounded enumeration (library expansion),
  each under the run contract.
- Bulk imports remain available if a blessed dataset appears; they land as sources with
  provenance like any other import.

**Revisit triggers** (any one reopens this decision):

- a capability needs provider-wide offline queries (for example, hash-sweeping the *entire*
  provider corpus rather than candidates);
- the retained fraction of a provider grows large enough that incremental sync of the remainder
  is cheaper than the live lookups it replaces (measure: retained posts > ~10% of provider);
- a maintained bulk dataset is blessed as a source.

**Performance rationale:** at 12 M+ provider posts the full-mirror costs (~21 GB+, ~62 k-request
refresh sweeps, ~62 M+ immutable rows obligating the audit tier) buy queries nothing asks for,
while every actual query class is already served by the retained corpus (offline joins) or the
bounded live surfaces (point lookups, enumeration). The floor measurement (1.7 KB/post, raw
payloads dominating) also bounds the *selective* path's future cost: a fully retained
10 k-artist library of ~2 M posts lands near 3.4 GB — comfortably in SQLite's range, with the
same query surface.
