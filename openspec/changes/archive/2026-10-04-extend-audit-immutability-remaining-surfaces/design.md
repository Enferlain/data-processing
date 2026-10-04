## Context

Migration 0012 closed the large enforcement gaps; its reviews identified the remaining
partial/convention-only surfaces, filed as Bead `data-processing-5de`. A mutation sweep over
src/ and tests/ (UPDATE/DELETE statements plus upserts) found zero delete statements on every
surface named below, plain-insert-only writers for `media_acquisition_verifications` and
`raw_payloads`, and only legitimate state-advance UPDATEs on the terminal-conditional tables
(two schema-audit tests already assert update rejection on plans/probes). See proposal.md.

## Goals / Non-Goals

**Goals:**

- Complete the audit-immutability sweep: deletion guards everywhere, full immutability for the
  two plain-insert surfaces, PK guards matching 0012 on the older run-input triggers.

**Non-Goals:**

- No table rebuilds beyond trigger drop/recreate; no data changes; no code changes; no new
  purge/redaction design (unchanged consequence: purge must supersede or tombstone).

## Decisions

### Unconditional no-delete alongside conditional update triggers

The six pre-0012 surfaces get plain no-delete triggers while their existing
update triggers stay untouched (terminal-conditional for requests and attempts, unconditional for the expansion surfaces) — deletion and update are independent
guarantees, and the sweep confirms nothing deletes. Alternative rejected: folding delete
guards into recreated conditional triggers (more churn for identical behavior).

### Full immutability for verifications and payloads

`media_acquisition_verifications` (declared/verified/comparison records) and `raw_payloads`
(byte content) are plain-insert-only with unique keys, so 0009-style no-update plus no-delete
applies directly. The payload guard makes the spec's "source reports and their payload content"
enforcement direct rather than transitive through the observations FK.

### PK-guard backport by trigger recreation

The 0006/0007 immutable-inputs triggers omit primary keys (0012 originally did too, fixed in
review). Migrations already shipped cannot be edited, but triggers can be dropped and recreated
in a later migration — the same technique 0010 used. The recreated triggers are byte-identical
plus the PK disjunct.

## Risks / Trade-offs

- [An unaudited write path breaks] → Same mitigation as 0012: the full suite exercises every
  writer under the triggers; any failure rescopes a trigger deliberately.
- [Recreated triggers drift from originals] → The migration copies the originals verbatim with
  one added line each; the schema tests asserting their messages still pass.

## Migration Plan

Migration 0013 only; additive triggers plus two trigger recreations. Rollback is the previous
schema version; no data is transformed.

## Open Questions

- None.
