# unified-discovery Specification

## Purpose
TBD - created by archiving change add-discovery-orchestration. Update Purpose after archive.

## Requirements

### Requirement: One input initiates a coherent discovery session
A URL (with optional held file and declared hash) or an existing record SHALL
initiate one discovery session that preserves the input's original identity and
provenance. URL inputs SHALL materialize through the operator seed path — the same
recognition, validation, and idempotent bundle identity as manual seeding — so
discovery and manual seeding can never disagree about identity. Session inputs,
steps, statuses, and outcomes SHALL be persisted and re-reportable by session id.

#### Scenario: URL input materializes once
- **WHEN** the same URL initiates discovery twice
- **THEN** the second session reuses the same seed post identity and records a new
  session against it

#### Scenario: Existing record input
- **WHEN** an existing post or account id initiates discovery
- **THEN** the session binds to that record without creating any new seed object

### Requirement: The planner reports every method with availability, exclusion, or a plan
Planning SHALL be offline and SHALL consider the local catalog and every registered
lookup-capable provider. Each considered (source, method) pair SHALL be reported as
planned, skipped with the source's capability reason, or excluded with why.
Provider plans SHALL be rendered only from strategies the provider declares for the
seed's resolved query material.

#### Scenario: Undeclared strategy is skipped with reason
- **WHEN** a provider does not declare a strategy the seed material would allow
- **THEN** the step records skipped with that capability reason rather than
  disappearing

#### Scenario: No material for a method
- **WHEN** the seed carries no material a method requires
- **THEN** the method is excluded naming the missing material

### Requirement: Execution is bounded, explicit about network, and failure-contained
Local steps SHALL execute offline as catalog queries. Provider steps SHALL execute
only under explicit live authorization, each through the bounded candidate lookup
machinery with its own budgets under a session-level request budget. A provider
failure SHALL be recorded as that step's typed outcome without discarding other
steps' results; without live authorization, provider steps SHALL remain planned.

#### Scenario: Offline by default
- **WHEN** a session runs without live authorization
- **THEN** local steps complete, provider steps stay planned, and no network access
  occurs

#### Scenario: Contained provider failure
- **WHEN** one provider's lookup fails during a live session
- **THEN** the session records that step's typed outcome and completes the remaining
  steps

### Requirement: Discovery results are evidence, not conclusions
Local and remote step results SHALL be retained through the existing candidate,
evidence, and run machinery; the session SHALL link them without duplicating them,
and SHALL NOT create identities, relationships, or matches beyond what that
machinery already justifies. A step returning no results SHALL record its searched
scope without asserting global nonexistence.

#### Scenario: Scoped empty result
- **WHEN** a step completes with zero results
- **THEN** the step records the scope searched and asserts nothing about sources
  not searched

### Requirement: file input kind

`catalog discover` MUST accept `--file <path>` as a standalone mutually
exclusive input (alongside `--url`, `--post`, `--account`, `--session`).
Sessions started this way MUST record input kind `local_file`, MUST execute
the offline local md5 search against the seed's verified hash, and MUST
report `local_source_url` and `local_platform_identity` as excluded naming
the material a file cannot carry. `--file` MUST remain usable as an
attachment to `--url` seeds exactly as today.

#### Scenario: file-only session plans honestly offline

- **WHEN** `catalog discover <catalog> --file <path>` runs without `--live`
- **THEN** the local md5 step executes, provider steps report as planned, and
  the session status reflects that provider steps are pending
- **WHEN** the same session re-runs with `--session <id>`
- **THEN** the report is reproduced without new provider requests

### Requirement: generation-scoped reporting

The session report MUST expose per-generation step outcomes as an additive
field; existing report keys MUST NOT change shape. Every (source, method)
pair MUST appear exactly once per session across generations, with duplicate
discoveries of the same reference collapsing to the first planned step.

#### Scenario: report shape is additive

- **WHEN** a session with generations is reported
- **THEN** pre-existing report consumers keyed on the old fields observe the
  same values as a single-generation session, and the new generation field
  carries the per-generation breakdown
