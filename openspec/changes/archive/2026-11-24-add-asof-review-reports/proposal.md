# Proposal

## What

Bead `data-processing-2ai` (parked follow-ons): operator-facing as-of
reports over the review ledgers.

- New `media_catalog/temporal.py`: pure read-only reconstruction —
  `review_state_snapshot(connection, as_of)` resolves every decision ledger
  (pair labels, account/post/attribution candidates, relationship reviews)
  to its latest decision at or before the cutoff, with pre-decision subjects
  excluded and reversals counted; `change_report(connection, start, end)`
  reports decisions, transitions and reversals, first-time labelings, new
  candidates, new relationships, landed observations, and finished runs
  inside the window.
- `catalog as-of <catalog> (--at T | --from T --to T) [--json]`: the snapshot
  or the change report, calendar-validated cutoffs, julianday comparisons
  (mixed whole/fractional second precision), human and JSON output.

## Why

The kernel requirement ("review state SHALL be the latest decision at or
before the cutoff") and the field-sources `--as-of` surface landed in
October; the review-ledger reconstructions and change reports were the
documented follow-ons with no surface. The ledgers now hold real history
(684 pair-label decisions, reversals included), so "what did we believe at
T" and "what changed between T1 and T2" are answerable questions operators
actually ask during calibration audits.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `provenance-kernel`: new requirement for the as-of report surfaces
  (snapshot + change report) implementing the existing reconstruction rule.

## Impact

- Code: `src/media_catalog/temporal.py` (new), `cli_commands/maintenance.py`
  (command registration + execute), `tests/test_temporal_asof.py`.
- Read-only; no schema changes; no new timestamps — the five-kinds
  vocabulary from `docs/plans/temporal-semantics.md` is used as-is.
