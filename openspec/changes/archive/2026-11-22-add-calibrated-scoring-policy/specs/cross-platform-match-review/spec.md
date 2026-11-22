## ADDED requirements

### Requirement: Candidate scoring is calibrated by family label rates

The versioned candidate-scoring policy SHALL derive each evidence family's
weight from the operator's recorded label distribution for the corresponding
signal family, carrying the family's label count, smoothed empirical rate,
and Wilson 95% interval into the score components. A family whose labels are
majority `different` SHALL contribute negative weight. Evidence families
that restate the same identity fact SHALL combine multiplicatively within
their correlation group, never additively. A policy change SHALL bump the
scoring version, and previously scored candidates SHALL keep the version
they were scored under.

#### Scenario: same-artist agreement alone scores negative

- **WHEN** a candidate's only supporting evidence is shared artist
  attribution and the same_artist label family is majority `different`
- **THEN** the candidate's score is negative and the components record the
  family rate and interval used

#### Scenario: correlated identity evidence compounds

- **WHEN** one candidate is supported by a source-URL reference and by
  same-artist attribution that restates the artist identity carried in that
  URL
- **THEN** the positive members combine as their probabilistic compound —
  never their plain sum — and the negative member discounts the compound
  without ever inflating it

#### Scenario: calibrated family outranks raw strength
- **WHEN** two single-evidence candidates differ only in evidence family
- **THEN** their scores order by calibrated family weight, not by the
  raw strength tier alone
