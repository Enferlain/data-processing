## ADDED requirements

### Requirement: As-of review snapshots and change reports

The system SHALL provide read-only as-of reports over the review ledgers: a
snapshot reconstructing every decision ledger's state at a cutoff (latest
decision at or before the cutoff; subjects undecided by then excluded;
reversals identified) and a change report between two cutoffs (decisions
and state transitions in the window, first-time decisions, newly created
candidates and relationships, observations landed, and runs finished).
Cutoffs SHALL be calendar-validated on parse and compared numerically so
mixed whole-second and fractional-second timestamps order correctly, and
the reports SHALL modify nothing.

#### Scenario: snapshot before a reversal

- **WHEN** a pair was labeled `unsure` in January and relabeled `different`
  in March, and the snapshot runs with a February cutoff
- **THEN** the pair reconstructs to `unsure`, the March decision is
  invisible, and no row changes

#### Scenario: change report counts a reversal

- **WHEN** the change report window covers January through March
- **THEN** the pair appears with both decisions, the transition counted as a
  reversal, and the window's new candidates and observations are reported

#### Scenario: malformed cutoffs are rejected

- **WHEN** a cutoff is not a valid ISO-8601 UTC instant
- **THEN** the command fails with a bounded diagnostic before any query
