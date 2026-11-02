# Design

## Context

Three proven subsystems anchor the slice. `SeedMaterializationService.materialize`
turns an operator bundle (recognized URLs, optional held file, declared MD5) into a
provenance-recorded stub post, idempotent by bundle digest. `plan_candidate_lookup`
resolves a catalog seed's private query material offline and renders per-strategy
plans against a provider's declared `LookupCapabilities`, emitting exclusions with
reasons. `CandidateLookupService` executes those plans under per-run budgets with
full run/request/result/checkpoint persistence and typed outcomes. The session layer
composes them; it invents none of the identity, evidence, or budget machinery.

## Goals and Non-Goals

Goals: one command from input → planned and (on request) executed multi-source
discovery with retained evidence; planner transparency (every considered method is
available, excluded-with-reason, or planned); offline by default; resumable
reporting.

Non-goals: external indexes (next unit), visual matching, multi-hop follow-ups,
URL-less seeds, downloads.

## Decisions

### D1: The session is a binder, not a parallel store

`discovery_sessions` records identity (input kind, seed post/account, bundle digest,
status, timestamps) and `discovery_steps` records one row per planned (source,
method): source kind (`local` or provider platform), method (search kind or lookup
strategy), status (`planned`/`complete`/`failed`/`skipped`), outcome summary, result
counts, and nullable `candidate_lookup_run_id`. All results live where they already
live — `candidate_lookup_runs`/`_results`, `post_match_candidates`, asset rows.
Roadmap §6: no parallel stores for the same facts.

### D2: Composition lives inside the discovery package

The orchestrator is `discovery/orchestration.py` — one home for everything
discovery-shaped (link extraction, candidates, review, and now session
orchestration), so no one hunts across parallel packages. The real adapter
construction moved to a shared `adapter_factory` module; link-driven fetch and
discovery delegate to it today, and the metadata commands' inline
constructions (identical in shape) migrate onto it incrementally.

### D3: Input normalization reuses seed materialization verbatim

URL inputs run through `SeedMaterializationService` (same recognition, same
file/MD5 validation, same idempotent bundle digest) so a `discover --url` and a
`seed create` can never disagree about identity. Existing records enter as
`POST:<id>`/`ACCOUNT:<id>` seeds. A file with no URL cannot become a stub post
today (the bundle requires a recognized platform identity); that input shape is
deferred, not approximated.

### D3: Local steps are SQL the catalog already answers

Local discovery answers three questions offline: does a verified or declared hash
match held assets (`asset_fingerprints` + asset verification facts); does a source
URL appear in retained external references; does the platform identity exist as a
record. Each becomes one local step with counts; local hits are evidence, never
identity claims (roadmap: search hits ≠ verified identities).

### D4: Provider steps are planned lookups, executed only under --live

The planner resolves the seed's material once (offline) and asks each registered
lookup-capable provider (`danbooru`, `aibooru`, `e621`, `gelbooru`) which
strategies it declares for that material; undeclared strategies become
`skipped` steps carrying the capability reason. Under `--live`, each provider step
executes through `CandidateLookupService` with its own `LookupLimits` bounded by a
session-level request budget; without it, provider steps remain `planned` and the
session reports the plan. Failures are contained per step (typed outcome recorded,
session continues), and a provider failure never discards local results.

### D5: Reporting is the session projection

`catalog discover` prints the session: input identity, per-step status/outcome/counts
(local results inline), and — when executed — the candidate summary for the seed via
the existing candidate machinery. `--session <id>` re-renders any prior session from
persistence alone. `--json` renders the same facts.

## Risks / Trade-offs

- Seed materialization requires a recognized URL for new inputs; the reference
  scenario's "arbitrary local image" lands in v2 with a URL-less seed shape. The
  session model does not assume otherwise.
- Budgets are two-dimensional and conservative: a session request budget and a
  session wall-clock budget shared across provider steps (a live run without the
  clock bound could stretch to per-step timeouts); richer cross-source budgeting
  arrives with P0.3.
- The planner's source registry is hand-registered now; P0.2's index adapters make
  it data-driven.

## Migration Plan

Forward-only `0024`: `discovery_sessions`, `discovery_steps` (+ indexes on session
id and seed post). No data migration; nothing referenced these tables before.

## Open Questions

- None blocking.
