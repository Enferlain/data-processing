# labeling Delta

## ADDED requirements

The labeling system SHALL offer a deterministic, seeded audit sample drawn
from populations the normal queue does not surface: auto-confirmed
identical-md5 pairs (re-verification of the auto rule), unlabeled
same-artist backlog pairs, and random available cross-artist pairs (pure
negatives, drawn from sampled post ids rather than a quadratic pair
enumeration). Audit pairs SHALL carry distinct `audit_*` queue signals,
SHALL be deduplicated against existing labels, and SHALL record verdicts
through the ordinary labeling flow.

#### Scenario: seeded audit sample is reproducible and disjoint

- **WHEN** the audit queue is built twice with the same seed and sample size
- **THEN** both builds offer the same pairs, none of which carry an existing
  label or a non-audit signal in the same build

#### Scenario: audit verdicts feed calibration

- **WHEN** audit pairs are labeled
- **THEN** the calibration report includes their `audit_*` families with
  verdict counts, rates, and Wilson 95% intervals alongside every other
  signal family

### Requirement: calibration report bounds every family from its labels

`catalog label-stats` SHALL report, per queue signal, the count of labels by
verdict, the same-or-variant rate, and a Wilson score 95% confidence
interval, computed from `pair_labels` alone.

#### Scenario: family report matches its labels

- **WHEN** a family holds known verdict counts
- **THEN** the report reproduces those counts and an interval containing
  the observed rate
