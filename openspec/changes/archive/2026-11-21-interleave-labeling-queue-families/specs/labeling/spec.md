## ADDED requirements

### Requirement: queue assembly interleaves signal families

The labeling queue SHALL assemble the per-session candidate list by
round-robin across signal families — one pair per family per rotation, in
the families' established order, preserving each family's internal pair
order — so no single family can monopolize a session. Interleaving SHALL
NOT change which pairs are eligible or skipped, pair attribution to the
first claiming family, or any pair's signal detail.

#### Scenario: dominant family no longer fills the session

- **WHEN** one family holds thousands of unlabeled pairs and every other
  family holds at least one
- **THEN** the session queue alternates families and each contributing
  family's pairs appear before the dominant family's second rotation

#### Scenario: family with nothing to offer is skipped in rotation

- **WHEN** a family has no eligible unlabeled pairs
- **THEN** rotation continues across the remaining families without gaps in
  the assembled queue
