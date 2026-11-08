# Design

See `docs/plans/search-indexing-design.md` (stage-2 design note) for the full
model: tiering, per-provider databases, raw-artifact separation, refresh
strategies, artist-identifier and reverse-image investigations. This document
covers only what slice 1 builds and the contracts later slices extend.

## Context

Stage 1 delivered: planner decisions per (target, method) with policy
filters and freshness from an attempt ledger keyed
subject × target × method × version × evidence; offline local steps; wave-A
fetch follow-ups from provider-lookup hits; `--dry-run`/`--search-state`.

## Goals / Non-Goals
Goals: registration + lookup-v1 projection + the e621 export importer, index
read path through the existing planner/executor/ledger, leads table + fetch
bridge, teach-on-result at the shared normalized-post boundary, maintenance
CLI.

Non-Goals (later): the danbooru snapshot importer (gated on the operator
supplying a concrete artifact; e621 is the first complete vertical slice),
refresh/download automation (`index refresh`, `cid` watermarks, `id_range`
sync), `artist_identifier` method, iqdb/phash tier-2 and reverse-image
tier-4 targets, semantic indexes.


## Decisions

### D1 — Index reads go through the planner, not a parallel engine

`plan_searches` gains registered-index target rows (kind `index`) using the
same material digests as provider steps; the executor dispatches index rows
to `search_index.lookup()` instead of an adapter. Reports, ledger attempts,
`--dry-run`, `--search-state`, and policy filters need zero new concepts.

### D2 — Snapshot revision rides the existing version column

Attempt `strategy_version` for index methods is
`lookup-v1@<snapshot_revision>` (revision = export checksum prefix or
dataset digest, from `index_meta`). Refresh ⇒ new version ⇒ replan, with the
verdict explaining "prior attempt under lookup-v1@abc… (current
lookup-v1@def…)".

### D3 — Registration in the catalog, projection outside it

`search_index_registrations` (migration 0032) holds the target name, provider
key for fetch routing, format, private path, revision mirror, timestamps —
mirroring `managed_roots` conventions. **The target name is the identity**;
the path is mutable plumbing, so moving the projection and updating the path
keeps history and freshness intact. The projection file lives under the
operator's indexes directory; the catalog never stores index rows.
`discovery_index_hits` (session-scoped leads) is the only new catalog data,
and only ever holds leads.

### D4 — Import is offline, streamed, atomic; artifacts retained untouched

`index import` reads the raw artifact (e621: gzip CSV streamed with bounded
memory), builds a temp projection, records `index_meta` (including the
artifact's path and digest), then `os.replace`s into place. Checksum
verification when supplied; failed import leaves the previous projection
untouched. The artifact itself is never modified or deleted — it is the
rebuild source; the projection is derived. Swap atomicity means concurrent
sessions see old-or-new, never partial. The danbooru snapshot importer is a
follow-up task in this change, gated on the operator supplying a concrete
artifact; e621 alone is the first complete vertical slice.

### D5 — Teaching at the shared post-commit normalized-post boundary

Every path that persists a provider post writes through `NormalizedPageWriter`
(`remote_sync/persistence.py`) — `catalog fetch` and direct metadata sync via
`MetadataSyncService`, candidate lookups via `CandidateLookupService`, and
discovery's provider/fetch steps through those same services (reprocess
re-confirms through the same writer). The hook lives there — once — not in
any caller: after a page's catalog transaction commits, the writer invokes
`search_index.teach(provider, post_identity)`, which opens the provider's
registered index (if any) and upserts with `origin='api',
last_confirmed_at=now`. Failure containment is structural: post-commit means
no catalog transaction can roll back from an index error; the hook wraps
everything and reduces any failure to a bounded diagnostic note on the run;
no registered index ⇒ no-op. No per-entry-point wiring exists to drift.

### D6 — Bridge reuses wave A

`_plan_followup` unions `discovery_index_hits` for the session's subject with
lookup-run hits when planning `fetch_post` steps; dedupe by (provider,
native id) already exists. Hits carry no trust: they are fetch suggestions.

## Risks / Trade-offs

- [e621 posts export is 1.86 GB; import time and disk] → streamed build,
  documented; artists/sources subsets can be imported without posts for
  identifier-only use later.
- [Danbooru snapshot format is unresolved] → the importer is a gated
  follow-up task in this change, started only when the operator supplies a
  concrete artifact; its layout is then verified and recorded in
  `index_meta.builder_version`. It cannot expand the e621 vertical slice.
- [Stale registrations (file missing at the recorded path)] → planner
  reports the index target excluded with the file problem named; discovery
  continues; re-pointing the registration at the moved file restores the
  same target identity and history.
- [Teaching doubles write work on fetches] → bounded upsert; measured
  negligible vs network cost.

## Migration Plan

`0032_search_index_registration.sql`: `search_index_registrations`,
`discovery_index_hits` (+ indexes). Additive; rollback is standard backup.

## Open Questions

- Danbooru snapshot source for the first real import (Jannchie HF dataset vs
  operator-provided CSV) — the importer starts only when the operator
  supplies the artifact; e621 is the first complete vertical slice either
  way, so this question gates a follow-up task, not the slice.
