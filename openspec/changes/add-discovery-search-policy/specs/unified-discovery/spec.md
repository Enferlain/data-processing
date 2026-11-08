# Spec Delta

## Purpose

Extend unified discovery planning and execution with search-policy decisions
(discovery-search-policy capability) while keeping sessions the unit of
subject-level reporting.

## MODIFIED Requirements

### Requirement: The planner reports every method with availability, exclusion, or a plan
Planning SHALL be offline and SHALL consider the local catalog and every
registered lookup-capable provider. Each considered (source, method) pair SHALL
be reported as planned, skipped with the source's capability reason or a fresh
prior attempt named, or excluded with why — including exclusions caused by the
run's search policy (source not included, method filtered, active search
disabled). Provider plans SHALL be rendered only from strategies the provider
declares for the seed's resolved query material. Each planned step SHALL carry
its query-evidence digest so prior attempts are comparable.

#### Scenario: Undeclared strategy is skipped with reason
- **WHEN** a provider does not declare a strategy the seed material would allow
- **THEN** the step records skipped with that capability reason rather than
  disappearing

#### Scenario: No material for a method
- **WHEN** the seed carries no material a method requires
- **THEN** the method is excluded naming the missing material

#### Scenario: Fresh prior attempt is skipped with provenance
- **WHEN** a (source, method) pair has a fresh successful prior attempt for
  the same subject, evidence, and strategy version
- **THEN** the step records skipped naming that attempt instead of being
  planned, and the planner performs no network access

### Requirement: Execution is bounded, explicit about network, and failure-contained
Local steps SHALL execute offline as catalog queries. Provider steps SHALL
execute only under explicit live authorization, each through the bounded
candidate lookup machinery with its own budgets under a session-level request
budget. A provider failure SHALL be recorded as that step's typed outcome
without discarding other steps' results; without live authorization, provider
steps SHALL remain planned. Steps not started when a budget runs out SHALL be
deferred rather than reported as attempted failures. Every executed step SHALL
record its outcome and the requests it spent in the durable attempt ledger. A
dry-run session SHALL stop after planning.

#### Scenario: Offline by default
- **WHEN** a session runs without live authorization
- **THEN** local steps complete, provider steps stay planned, and no network
  access occurs

#### Scenario: Contained provider failure
- **WHEN** one provider's lookup fails during a live session
- **THEN** the session records that step's typed outcome and completes the
  remaining steps

#### Scenario: Budget boundary defers unstarted work
- **WHEN** the session budget is spent with steps still queued
- **THEN** those steps end deferred with a budget outcome and later runs may
  resume them
