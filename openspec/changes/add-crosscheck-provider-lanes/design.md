# Design

## Context

`run_crosscheck` walks subjects → providers → strategies on one connection;
each lookup's ~0.4s round-trip idles the other providers. The catalog is WAL
(`PRAGMA journal_mode = WAL` set unconditionally in `database.py`), every
connection carries `busy_timeout = 5000`, and the per-provider pacing floor
lives inside `CandidateLookupService`.

## Decisions

- **Per-provider lanes, not a general pool.** Each provider gets exactly one
  worker; within the lane everything stays sequential — subject order,
  per-item reuse checks, pacing (the service's interval logic is untouched,
  and single-lane sequencing makes the per-provider floor hold trivially).
  Provider-disjoint lanes mean `crosscheck_items` rows never collide across
  lanes (the unique key includes provider).
- **One connection per lane** (`CatalogDatabase` on the same path): WAL lets
  lanes read concurrently and serializes writers; short item commits under
  the 5-second busy timeout make blocking brief and deadlock impossible (a
  WAL writer waits for the write lock; it never waits on a lane holding
  row locks while waiting on another lane). The coordinator holds the
  original connection for batch open/stop and the final summary.
- **Budgets and stops are coordinator-owned.** A lock guards
  `requests_used` and the deadline check; each lane consults the shared
  budget before issuing a request and a shared stop flag between items, so
  budgets still stop at item boundaries and the first stop reason wins.
  Lane-local counts merge after the join — no shared mutable counters.
- **Lane failure is contained.** A lane-level exception sets the stop flag
  from inside the lane (sibling lanes stop issuing requests promptly), and
  is re-raised after the join.
- **Budgets reserve per in-flight item.** The check under the lock counts
  `requests_used + in_flight` (each lane reserves one request for an item
  it is about to execute and returns the reservation when it lands), so N
  lanes cannot each pass an unreserved check; the overrun bound returns to
  the sequential one — a single item's pagination may exceed the budget.
- **Counting is lane-free.** `pending` is the durable row count from the
  batch summary (subjects a stopped lane never reached have no rows and
  resume on re-run), and `metadata-only` is a coordinator prepass over
  post subjects — neither scales with lane count.

## Risks

- Three-to-four WAL writers briefly contend; worst case a commit waits up to
  the busy timeout. Item commits are milliseconds; observed contention in
  testing is zero waits at 2–4 lanes.
- `python -X freeze...` style thread-accounting is not needed: threads only
  wrap the existing synchronous service; no async refactor.

## Migration Plan

None — no schema change.
