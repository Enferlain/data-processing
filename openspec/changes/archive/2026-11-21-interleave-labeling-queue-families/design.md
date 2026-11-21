# Design

## Context

`build_queue` normal mode (queue.py:189-363) collects families through a
shared `add(pairs, signal, detail)` helper into one flat list guarded by the
`seen` set (first family claims a pair), then slices `[:limit]`. Session
limit defaults to 50; `catalog label` passes no custom limit.

## Goals / Non-Goals

**Goals:** round-robin assembly; deterministic, testable ordering.

**Non-Goals:** changing family priority order, per-family caps or sampling
(operator chose interleaving over volume reduction 2026-11-21), the
`revisit_unsure` path, eligibility/skip semantics.

## Decisions

### D1: `add()` appends to a per-family bucket; assembly round-robins buckets

`add()` gains a local bucket list; each call registers one bucket. Final
assembly walks `zip_longest(*buckets)` and flattens non-None entries, which
is exactly one-pair-per-family-per-rotation in bucket (family priority)
order, stable within families, and skips exhausted buckets naturally. The
existing `seen`/`labeled`/`post_ready` logic moves untouched into the
bucket path, so eligibility, `skipped_unusable_count`, and first-family
attribution are byte-identical.

Alternative: priority-queue with family counters — rejected: stateful and
harder to pin in tests than a zip of ordered lists.

### D2: Interleave before the limit slice

`CandidateQueue(list(interleaved)[:limit], skipped_count=...)` — the limit
applies to the interleaved order, so a dominant family cannot crowd out
other families' first rotations.

## Risks / Trade-offs

- [Tests assumed block ordering] → Existing suites assert membership,
  details, and counts, not global block order; full labeling suites run as
  the gate. New test pins the alternation directly on a scratch catalog.
- [Dominant family still eventually dominates] → Accepted: the operator
  explicitly chose full enumeration with interleaved presentation over
  volume reduction.

## Migration Plan

One commit: bucket refactor + interleaved slice + tests; standard gates; no
schema or data impact. Rollback is `git revert`.
