# Design

## Context

Decision ledgers: `pair_label_decisions` (prior_verdict/verdict/decided_at,
first decision = initial labeling), `account/post/attribution_candidate_decisions`
(prior_state/decision/decided_at), `relationship_review_decisions` +
`relationships` (birth review_state, transitions via decisions). Candidates
carry `created_at`. The reconstruction rules are fixed in
`docs/plans/temporal-semantics.md` and the kernel spec; field-sources
`--as-of` established the julianday comparison idiom for mixed precision.
CLI precedent: read-only report commands in `cli_commands/maintenance.py`
(`label-stats`).

## Goals / Non-Goals

**Goals:** snapshot + change report over all five ledgers; validated
cutoffs; deterministic ordering; zero writes.

**Non-Goals:** as-of on current-column projections (posts/assets — needs
full observation replay, a separate follow-on), provenance timelines,
exported artifacts (the reports are CLI surfaces), attribution worklist
reconstruction (a consumer view; same queries can power it later).

## Decisions

### D1: Reconstruction in SQL window functions, latest-wins by julianday

Per ledger, latest decision ≤ cutoff = the row ranked first by
`julianday(decided_at), <decision_pk> DESC` over the ≤-cutoff set
(the pk tiebreak fixes same-instant decisions deterministically). Pair
labels join their latest decision for verdict-at-T plus the label's signal;
subjects whose first decision is after the cutoff do not exist yet.

### D2: Birth-state reconstruction for relationships

A relationship's state at T is its latest decision ≤ T; with no decision
≤ T it is the birth state — taken from the earliest decision's
`prior_state` when any decision exists (the ledger records what it
transitions from), else the current `review_state` (valid exactly when the
relationship was never decided).

### D3: One command, two modes

`catalog as-of <catalog> --at T` → snapshot; `--from T --to T2` → change
report (half-open window: start < entry ≤ end, so chaining windows
partitions history). Both accept `--json`. Cutoffs parse via
`datetime.fromisoformat` after Z-normalization — calendar validation —
rejecting naive timestamps.

### D4: Change report covers decisions plus arrivals

In-window: decisions by ledger with transition counts (reversal = decision
differing from its own prior), first-time pair labelings, candidates
created, relationships created, raw observations landed (by object_kind),
remote runs finished. Arrivals use the observation/run timestamps per the
five-kinds vocabulary, never provider-claimed times.

## Risks / Trade-offs

- [Ledger skew (a decision predating its subject's creation)] → Reports
  read ledgers as recorded; a skew row counts at its own decided_at —
  history is immutable either way and the volumes (684 rows) make skew
  visible, not silent.
- [Same-instant decisions] → pk tiebreak makes output deterministic.

## Migration Plan

Single commit, read-only surface; rollback is `git revert`.
