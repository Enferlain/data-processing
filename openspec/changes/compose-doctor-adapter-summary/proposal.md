# Proposal

## Why

The maintainer asked for one doctor: after `add-adapter-doctor`, `catalog doctor` still
reported only storage integrity while adapter contract health lived on a separate
command. One command should answer "is everything healthy" — catalog storage and the
adapter contracts both.

## What Changes

- `catalog doctor` composes the adapter doctor's **offline** replay summary into its
  report: an `adapters` object with overall ok, per-surface ok, named failures, and
  doctor-level errors, alongside the existing integrity/foreign-key/schema facts.
- Full per-case detail and `--live` probing stay on `catalog adapter-doctor`; the
  composed summary never touches the network.
- Exit semantics of `catalog doctor` are unchanged (it remains report-only; the
  dedicated adapter-doctor command carries the nonzero-exit contract).

### Non-goals

- Live probing or per-case detail on the catalog doctor, exit-code changes, and any
  mutation/repair behavior (both doctors stay read-only).

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `adapter-doctor`: its offline replay results also surface, as a compact summary,
  inside the catalog doctor's report.
