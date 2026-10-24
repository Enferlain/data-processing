## Context

The pool fetch (change `add-danbooru-pool-collection`) established the shape for bounded
non-default-sync single-object operations: vocabulary value via table rebuild, service-shaped run
contract (run commits first, fetch outside the transaction, raw retained for every response,
provider faults end `failed`, transport errors auditable), digest-deduplicated append-only
observations. This change applies that shape to post-attached text three times, reusing every
decision rather than reopening it.

## Goals / Non-Goals

Goals: opt-in commentary and notes fetches for three providers; two observation tables; real
fixtures where live capture is possible; every default-sync path untouched.

Non-Goals: e621 note *versions* history endpoint (the note row's current version is retained; the
per-version history is deeper provenance for a later change); deriving tags/attribution from
commentary text; translation fetching beyond what the provider reports; default-sync integration;
the gelbooru HTML transport (dapi only).

## Decisions

### D1: Two tables, not one — commentary is a caption, notes are positioned overlays

`post_commentary_observations` (original/translated title + description; one observation per
digest) and `post_note_observations` (note native id, body, x/y/width/height, e621 version; one
observation per (post, note id, digest)). A single generic "text surface" table would trade two
clear schemas for a NULL-heavy compromise; the family split matches the data.

### D2: Enrichment requires a retained post

Unlike pools (whose members may not be retained), commentary/notes fetch by *our* post's native id:
the operation is defined as enriching catalog posts. An unknown native id is refused with a clear
error before any run starts. This also keeps `post_id` non-null on both tables.

### D3: Digests cover the text facts, not the timestamp

Commentary digest = sha256 over (original title, original description, translated title,
translated description); note digest = sha256 over (note id, body, x, y, width, height, version).
Unchanged re-observation dedups; any edit, move, or version bump lands a new row; `observed_at`
never participates (re-seeing the same text at another time is the same observation).

### D4: The enrichment module owns the run contract once for all three providers

`remote_sync/enrichment.py` exposes `fetch_commentary(database, adapter, native_post_id)` and
`fetch_notes(database, adapter, native_post_id)` with one shared internal flow (the pool-fetch
shape). Provider-specific parsing lives beside the flow: danbooru's commentary endpoint returns a
list (0–1 entries) of commentary objects; e621 and gelbooru return lists of note entries. Empty
lists are successful empty observation sets — absence is not a retained fact.

### D5: Gelbooru's contract is provisional by fixture provenance

No dapi credentials exist in this environment, so the gelbooru fixture is synthetic, built from
the modern dapi wrapper shape the repo's own post/tag parsers already handle
(`{"@attributes": ..., "note": [...]}`; a bare array is also accepted as the legacy form) and
labeled as such inside the fixture file. The spec names the
provisionality; a follow-up bead replaces the fixture with a live capture when credentials are
available, and only that replacement can bless the shape.

## Risks / Trade-offs

- [Synthetic gelbooru fixture could encode a wrong shape] → The fixture carries its provenance
  label; the follow-up bead blocks "verified" status for that surface; everything else (run
  contract, storage, dedup) is shape-independent.
- [Big posts with hundreds of notes] → One bounded request; SQLite handles hundreds of rows
  trivially; no pagination on any of these endpoints at one post.
- [Commentary text is user content] → Retained as provider-reported text exactly like tags and
  descriptions already are; no sanitization beyond storage.
- [Third operation-vocabulary rebuild in three migrations] → Mechanical and verified each time;
  bead `data-processing-6y1` owns the longer-term vocabulary decision.

## Migration Plan

Migration 0017 adds the two tables (append-only triggers from day one) and rebuilds the three
remote-operation tables with `fetch_commentary` and `fetch_notes` added to the CHECK lists — the
0010/0016 idiom, preserving every row, constraint, index, and trigger. No backfill. Rollback: drop
the two tables and rebuild back, or restore from backup.

## Open Questions

None blocking. Whether e621 note-version history deserves its own surface is deferred until a
consumer needs per-version provenance.
