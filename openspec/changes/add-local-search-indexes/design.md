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

Goals: registration + lookup-v1 projection + two importers (e621 export,
danbooru snapshot), index read path through the existing planner/executor/
ledger, leads table + fetch bridge, teach-on-result, maintenance CLI.

Non-Goals (later slices): refresh/download automation (`index refresh`,
`cid` watermarks, `id_range` sync), `artist_identifier` method, iqdb/phash
tier-2 and reverse-image tier-4 targets, semantic indexes.

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

`search_index_registrations` (migration 0032) holds target name, provider key
for fetch routing, format, private path, revision mirror, timestamps —
mirroring `managed_roots` conventions. The projection file lives under the
operator's indexes directory; the catalog never stores index rows.
`discovery_index_hits` (session-scoped leads) is the only new catalog data,
and only ever holds leads.

### D4 — Import is offline, streamed, atomic

`index import` reads the raw artifact (e621: gzip CSV streamed with bounded
memory; danbooru: metadata snapshot file), builds a temp projection,
records `index_meta`, then `os.replace`s into place. Checksum verification
when supplied; failed import leaves the previous projection untouched.
Swap atomicity means concurrent sessions see old-or-new, never partial.

### D5 — Teaching is a completion-path hook with failure containment

One function `teach_provider_result(database, provider, post_identity)` is
called from fetch/lookup step completion in the orchestrator. It opens the
provider's registered index (if any), upserts with
`origin='api', last_confirmed_at=now`, and converts any error into a step
detail note. Catalog transactions are already committed at that point, so
index writes can never roll back catalog truth.

### D6 — Bridge reuses wave A

`_plan_followup` unions `discovery_index_hits` for the session's subject with
lookup-run hits when planning `fetch_post` steps; dedupe by (provider,
native id) already exists. Hits carry no trust: they are fetch suggestions.

## Risks / Trade-offs

- [e621 posts export is 1.86 GB; import time and disk] → streamed build,
  documented; artists/sources subsets can be imported without posts for
  identifier-only use later.
- [Danbooru snapshot format varies by dataset] → importer works from a
  declared column map; the exact Jannchie layout is verified at
  implementation time and recorded in `index_meta.builder_version`.
- [Stale registrations (file moved/deleted)] → planner reports the index
  target excluded with the file problem named; discovery continues.
- [Teaching doubles write work on fetches] → bounded upsert; measured
  negligible vs network cost.

## Migration Plan

`0032_search_index_registration.sql`: `search_index_registrations`,
`discovery_index_hits` (+ indexes). Additive; rollback is standard backup.

## Open Questions

- Danbooru snapshot source for the first real import (Jannchie HF dataset vs
  operator-provided CSV) — resolved when the operator supplies the artifact;
  the importer contract is fixed either way.
