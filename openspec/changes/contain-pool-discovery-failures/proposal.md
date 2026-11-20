# Contain Per-Name Failures in Pool Discovery

## What

`discover_pools`'s per-name loop now catches exceptions from `search_pools`,
records a `{"name", "artist_held_posts", "pools_found": 0, "outcome": "failed",
"error"}` entry (error string capped at 200 chars), charges one request against
the budget, and continues with the next name.

## Why

A live overnight pass (2026-11-20, `--discover-names 600`) died five minutes in
on an uncontained `httpx.ReadTimeout` — one network hiccup aborted the whole
sweep, losing every remaining name. `sweep_artists` already contains per-name
failures the same way; pool discovery now matches that contract.

## Scope

In:

- try/except around the `search_pools` call in the discovery loop.
- Regression test: one name raises, the pass continues, both outcomes recorded.

Out:

- Retry logic (the next discovery pass retries failed names naturally — they
  have no complete run to skip on).
- Any change to `search_pools` itself or its error types.
