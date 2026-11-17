## Proposal

### What

`run_crosscheck` executes providers concurrently in per-provider lanes —
each lane a sequential subject loop on its own WAL connection with its own
adapter and pacing — while aggregate budgets, batch state, and reporting
stay coordinator-owned.

### Why

The sweep is latency-bound, not rate-bound: sequential per-subject lookups
cost ~0.4s round-trip each while other providers idle (measured 2026-11-14:
2.6 req/s aggregate on the file-seeds sweep; the per-provider pacing floors
are satisfied free by the three-way interleave and never bind). Lanes make
the HTTP waits overlap: with N providers, wall time per subject drops from
the sum of round-trips to roughly one. Bead `data-processing-jq1`.

### Scope

- `run_crosscheck` restructure only; CLI, schema, batch keys, budgets,
  reuse checks, and per-item outcomes unchanged.
- Spec delta on the sequential-lookups clause (MODIFIED): lanes are
  provider-disjoint and each internally sequential; writes serialize
  through WAL with the existing busy timeout.
- Tests: correctness under concurrency (all providers' items recorded,
  counts aggregate exactly), lane overlap observed, budget stop honored
  across lanes.
- Out of scope: parallelism within a provider, parallel subjects per
  provider, the discovery/metadata surfaces.
