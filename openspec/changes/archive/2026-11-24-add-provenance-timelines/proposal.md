# Proposal

## What

Bead `data-processing-2ai` (final follow-ons): provenance timelines and
accounts-as-of.

- `media_catalog/temporal.py` gains `timeline(connection, *, post_id |
  account_id, limit)`: the chronological evidence chain for one subject —
  raw observations (with their originating remote/import run), metadata
  observations, account snapshots (account subjects), pair labels and their
  decisions, match candidates and their decisions, relationships and their
  review decisions — sorted by parsed time, bounded, read-only.
- `review_state_snapshot` gains an `accounts` section: accounts known at the
  cutoff (first snapshot ≤ T) with snapshot volume, from the append-only
  `account_snapshots` history.
- `catalog timeline <catalog> (--post N | --account N) [--limit] [--json]`
  in `cli_commands/maintenance.py`.

## Why

The temporal-semantics follow-on list names "provenance timelines for
debugging why a current projection changed" — with 47,802 account snapshots
and a growing observation/decision history, "what happened to this subject,
when, from which source" is now an operator question the retained history
can answer directly. The attribution-worklist-as-of follow-on stays parked:
the relationships table holds one row, so the worklist it would reconstruct
does not exist yet (revisit when review volume makes it real).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `provenance-kernel`: the as-of reports requirement extends with subject
  timelines and accounts-at-a-cutoff.

## Impact

- Code: `src/media_catalog/temporal.py`, `cli_commands/maintenance.py`,
  `tests/test_temporal_asof.py`. Read-only; no schema changes.
