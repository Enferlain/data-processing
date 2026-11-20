## Proposal

### What

`catalog metadata sankaku-sweep`: bounded bulk listing of the catalog's top
artist names through the existing sankaku keyset listing (`LIST_ACCOUNT_POSTS`),
with prior-run skipping, a request budget, platform-floor pacing — and a
post-sweep **md5 overlap report**: how many listed sankaku posts carry an md5
already known on another platform versus md5s new to the catalog.

### Why

The operator's sankaku direction (bead `data-processing-hvs`, recorded
2026-11-19) is artist-anchored expansion with new-content harvesting, not just
crosscheck. Phase 2 (search artists, pull their listings) and the md5 half of
phase 3 (compare) need no new provider capabilities: the listing is shipped
and fixture-backed, and community research (`84v`, closed) confirmed keyset
tag search is the path. Similarity comparison stays open (`ry2` — method
undecided); media pulls and new-content acquisition are later phases.

### Scope

- `remote_sync/artist_sweep.py`: cross-platform ranked artist names (floor of
  3 held posts), per-name sync through the standard contract, skip on prior
  complete listing runs, per-name failure containment, request budget +
  platform-floor pacing, and the read-only md5 overlap report.
- CLI `catalog metadata sankaku-sweep` (discover-only; single-artist listing
  remains `sankaku-list`), tests, docs, changelog.
- Out of scope: media/sample downloads, similarity, new-content ingest,
  md5 lookup surface (phase 1, needs credentials + live fixture).
