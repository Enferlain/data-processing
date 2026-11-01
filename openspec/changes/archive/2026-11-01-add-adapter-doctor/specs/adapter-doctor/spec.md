# Spec Delta

## ADDED Requirements

### Requirement: The doctor replays every adapter's captured contract offline
The doctor SHALL replay every registered suite-format fixture case under the current
adapters without network access. For each case it SHALL verify that the suite's pinned
adapter and schema versions match the live adapter's, that the expected outcome matches
(success cases normalize; failure cases raise the named typed outcome), that expected
post and account identifiers are a subset of the normalized top-level identifiers, and
that every top-level normalized item attributes itself to the suite's platform. Any
failure SHALL be reported with the suite name, case name, and a specific reason.

#### Scenario: A normalizer regression is named
- **WHEN** a replayed case no longer normalizes as its expected facts declare
- **THEN** the doctor reports the suite, case, and mismatching check, and exits nonzero

#### Scenario: All suites green
- **WHEN** every registered case replays cleanly
- **THEN** the doctor reports success per surface and exits zero

### Requirement: Live probes are explicit, bounded, and credential-honest
With `--live`, the doctor SHALL issue exactly one metadata request per platform through
the real adapter at that adapter's pacing floor, targeting the identifier its own
captured contract already covers, and SHALL normalize the live response under the
current schema. Missing credentials SHALL report the platform as skipped with the named
credential reason rather than as success or failure. The `--live` flag SHALL be the
operator authorization; no live request SHALL occur without it, and credential values
SHALL never appear in output, logs, or identities.

#### Scenario: Anonymous platform probes clean
- **WHEN** `--live` runs and an anonymous platform answers a normalizable response
- **THEN** the platform reports success with request outcome, latency, and body size

#### Scenario: Credentials absent
- **WHEN** a credentials-required platform has no resolved credentials
- **THEN** the platform reports SKIPPED with the missing credential names and the run
  neither fails nor counts it as verified

#### Scenario: Provider-side deletion
- **WHEN** a probed identifier no longer exists upstream
- **THEN** the doctor reports the adapter's typed outcome for it instead of schema drift

### Requirement: The doctor report is complete and machine-readable
The doctor SHALL render a per-surface report covering offline replay results and, when
live, probe outcomes, and SHALL offer a JSON rendering with the same facts. The exit
status SHALL be nonzero if and only if any check fails.

#### Scenario: Machine consumption
- **WHEN** `--json` is passed
- **THEN** the report is a single JSON object with one entry per registered surface and
  per-check failure reasons
