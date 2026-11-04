# Spec Delta

## Purpose

Extend unified discovery sessions with the local-file input kind and
generation-scoped reporting.

## ADDED Requirements

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
