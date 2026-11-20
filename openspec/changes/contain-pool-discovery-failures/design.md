# Design

## Context

`discover_pools` drove `search_pools` per ranked artist name with no exception
boundary; `sweep_artists` (shipped hours earlier) already demonstrated the
per-name containment pattern (`outcome: failed`, error string snapshot, budget
charged, continue).

## Decision

Mirror the artist-sweep pattern exactly rather than catching only
`httpx.HTTPError`: a `ValueError` from a malformed name or an unexpected
adapter error is equally non-fatal for the pass, and the entry's `error` field
preserves the type name for triage. Charging the failed name one request keeps
the budget honest (the request was attempted; retry cost is paid by a later
pass). No retry inside the pass: a failed name leaves no complete run, so the
next discovery pass retries it naturally through the existing skip logic.
