# discovery-search-policy Specification

## Purpose

Operator control and transparency over discovery searching: what is searched,
against which targets, by which methods, whether prior attempts are fresh,
what is queued/deferred/running, and what actually happened — persisted and
inspectable without repeating work.

## Requirements

### Requirement: one policy governs a discovery run

A search policy SHALL be a single explicit object covering: the subjects to
search, the search targets included or excluded (the local catalog and each
lookup-capable provider are targets; future index or search-service targets
use the same vocabulary), the methods allowed, whether only evidence-following
(trails) searches or also active searches may run, the recheck mode, and the
existing request/time budgets. The CLI SHALL map flags onto this policy and
reject unknown target or method names rather than silently matching nothing.
`--include-source` SHALL restrict the target set to the named sources;
`--exclude-source` SHALL remove named sources from the default set; using
both SHALL be rejected.

#### Scenario: unknown source name is rejected

- **WHEN** a run is started with `--include-source danboru` (a misspelling)
- **THEN** the command fails naming the valid target names and nothing is
  planned or executed

#### Scenario: include restricts, exclude removes

- **WHEN** a run includes only `danbooru` and `catalog`
- **THEN** every other provider's steps are excluded naming the policy
- **WHEN** a run excludes `e621`
- **THEN** e621 steps are excluded naming the policy and all other targets
  remain eligible

### Requirement: search state identity

Retained search state SHALL be keyed by subject × search target (kind and
source) × method × strategy version × query-evidence digest. A completed
attempt against one target or method SHALL NOT imply anything about any other
target or method for the same subject. Query evidence SHALL be part of the
key: when a subject's applicable query material changes, the prior attempts
do not cover the new evidence and the step is planned again. The strategy
version SHALL be part of the key: attempts recorded under an older strategy
version are not fresh under a newer one.

#### Scenario: one provider's success never satisfies another

- **WHEN** a subject's `danbooru / verified_md5` attempt succeeded and
  `aibooru / verified_md5` was never attempted
- **THEN** a later run still plans `aibooru / verified_md5`

#### Scenario: changed evidence replans

- **WHEN** a subject gains a newly verified hash after a successful search
  that did not include it
- **THEN** the search step keyed on the new evidence is planned again even
  under the default recheck mode

### Requirement: recheck modes and freshness

The recheck mode SHALL be one of `unsearched` (default), `stale`, or `force`.
An attempt SHALL be considered fresh only when its key matches the current
evidence and strategy version, it completed successfully, and — under `stale`
mode — it finished within the policy's staleness age. Under `unsearched`, any
key with a fresh successful attempt SHALL be skipped with the prior attempt
named; failed, partial, or interrupted attempts SHALL never count as fresh.
Under `stale`, additionally successful attempts older than the staleness age
SHALL be replanned. Under `force`, prior attempts SHALL not suppress any
applicable step. Zero-result successful attempts SHALL count as fresh
completed searches.

#### Scenario: rerun skips completed work by default

- **WHEN** the same discovery request runs again after every step completed
  successfully
- **THEN** each previously successful step is skipped as fresh, naming the
  prior attempt, and no local or remote work repeats

#### Scenario: failed attempts are retried

- **WHEN** a step failed or was deferred in a prior run
- **THEN** a later run plans it again under the default recheck mode

#### Scenario: force re-executes

- **WHEN** a run uses `--recheck force`
- **THEN** applicable steps execute again regardless of prior successes

#### Scenario: staleness replans old successes

- **WHEN** a run uses `--recheck stale --stale-after 7d` and the only
  successful attempt for a step finished more than seven days ago
- **THEN** that step is planned again

### Requirement: dry-run planning

A run invoked with dry-run SHALL produce the full plan report — every target ×
method with its decision and reason, including freshness skips — without
executing any step, local or remote, and without recording new attempts.

#### Scenario: dry-run executes nothing

- **WHEN** a discovery run uses `--dry-run`
- **THEN** all steps remain in the planned/skipped/excluded state the planner
  assigned, local steps do not execute, and the attempt ledger is unchanged

### Requirement: search-state inspection

The operator SHALL be able to inspect, per subject and offline, every
considered target × method: whether it is applicable, its query-evidence
digest, the latest attempt's time, outcome, result count, searched scope,
strategy version, and its freshness verdict under a supplied policy.

#### Scenario: inspect after a live run

- **WHEN** search state is inspected for a subject that was searched live
  earlier
- **THEN** the report shows, per target and method, the recorded attempt
  details and the freshness verdict under the given recheck policy, without
  any network access

### Requirement: queue states and deferral

Steps SHALL carry queue-relevant states: planned (queued, not started),
running, complete, failed, deferred, skipped, and excluded. A step not started
because the run's budget ran out SHALL be `deferred` with a budget outcome —
distinct from an attempted failure — and SHALL be planned again by a later
run. The run report SHALL include counts by step status and the requests used
by each session.

#### Scenario: budget exhaustion defers instead of failing

- **WHEN** a run's request budget runs out with provider steps still queued
- **THEN** those steps are deferred naming the budget boundary, and the run
  does not report them as attempted failures

#### Scenario: deferred work resumes

- **WHEN** a run is repeated after a prior run deferred steps
- **THEN** only the deferred and never-searched steps execute; previously
  successful steps stay skipped as fresh

### Requirement: multi-subject runs and progress

A discovery run SHALL accept multiple explicit subjects and execute them in a
deterministic order (input order, then plan order) under one shared request
and time budget, with existing per-provider pacing. The report SHALL include
aggregate progress: per-status step counts across subjects, per-subject
session results, and remaining budget. Execution within a run SHALL be
sequential; adding concurrency later MUST NOT change the persisted states.

#### Scenario: shared budget across subjects

- **WHEN** a multi-subject live run's shared request budget is exhausted partway
- **THEN** remaining steps across all remaining subjects are deferred, not
  executed, and the report names the totals per subject and status

#### Scenario: repeated multi-subject run repeats no successful work

- **WHEN** the same multi-subject command runs again
- **THEN** previously successful subject × target × method steps are skipped
  as fresh and the run reports near-zero new work

### Requirement: trails versus active search

Methods that search by artist name, alias, free text, or (in future) other
derived queries SHALL be classed as active; methods that follow known
references, stable ids, and hashes SHALL be classed as trails. With active
search disabled (the default), active methods SHALL be excluded naming the
policy. Supplying an artist search term SHALL imply active search so existing
account-seed invocations keep planning artist strategies.

#### Scenario: trails-only excludes artist methods

- **WHEN** a run plans artist strategies without active search enabled
- **THEN** those steps are excluded naming the disabled active search

#### Scenario: search term implies active search

- **WHEN** an account-seeded run supplies `--search-term`
- **THEN** artist strategies remain plannable exactly as before this policy
  existed

### Requirement: attempt retention answers history

The durable attempt ledger SHALL let later interrogations answer, for any
subject: whether a target was searched with a given method, when, under which
strategy version and evidence, with what scope and outcome — including
zero-result, failed, and deferred histories — after process restarts and
catalog reopen. Attempts SHALL be append-only history linked back to their
session and step.

#### Scenario: state survives reopen

- **WHEN** a catalog with prior discovery attempts is reopened and search
  state is inspected
- **THEN** every prior attempt remains reportable with its timing, scope, and
  outcome

#### Scenario: zero results record scope, not nonexistence

- **WHEN** a step completes with zero results
- **THEN** the attempt records the searched scope and result count zero, and
  nothing in the report asserts the subject is absent from the target
