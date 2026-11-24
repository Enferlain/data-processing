# Design

## Context

Retained history per subject: `raw_observations` (platform + native id,
observed_at, remote/import run), `post_metadata_observations` (post_id,
engagement fields, raw link), `account_snapshots` (account_id, profile
fields, append-only), `pair_labels`/`pair_label_decisions` (either endpoint),
`*_match_candidates` + decisions (subject or target), `relationships` +
`relationship_review_decisions` (subject or target). The as-of snapshot
machinery from `add-asof-review-reports` already owns cutoff validation and
the julianday ordering idiom.

## Goals / Non-Goals

**Goals:** one command answering "what happened to this subject, when, from
which source"; accounts-known-at-cutoff in the snapshot; read-only; bounded.

**Non-Goals:** diffing snapshots field-by-field (the timeline lists events;
field comparison stays a field-sources concern), attribution-worklist as-of
(parked: one relationship row exists), new retention.

## Decisions

### D1: One event list, uniform shape

Every event renders as `{at, kind, detail}` — `at` the parsed timestamp,
`kind` a stable vocabulary (`source_observation`, `metadata_observation`,
`account_snapshot`, `pair_label`, `label_decision`, `candidate`,
`candidate_decision`, `relationship`, `review_decision`), `detail` the
source-specific facts (provider + operation or import kind; field names
touched; verdicts with priors). Sorted by `julianday(at)`, then a stable
secondary key.

### D2: Run provenance joins one level deep

Each raw observation names its remote run (operation + status + origin) or
import run (source_kind) inline — enough to answer "which sweep produced
this" without a second query surface.

### D3: Accounts-at-cutoff rides the snapshot report

`review_state_snapshot` gains `accounts`: `known` (accounts with a first
snapshot ≤ T) and `snapshots_retained` (rows ≤ T) — the account analogue of
the candidate/relationship sections, from the same append-only ledger
discipline.

## Risks / Trade-offs

- [Wide detail payloads] — Detail fields are allowlisted per kind; nothing
  renders free text beyond bounded note excerpts.

## Migration Plan

Single commit, read-only surface; rollback is `git revert`.
