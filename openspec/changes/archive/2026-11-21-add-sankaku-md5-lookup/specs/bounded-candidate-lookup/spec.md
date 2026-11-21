## ADDED requirements

### Requirement: Candidate lookup supports bounded Sankaku md5 evidence searches

Candidate lookup SHALL allow Sankaku as an explicit provider for the
`declared_md5` and `verified_md5` strategies only, under the same bounded run
contract, pacing floor, and candidate-only outcomes as every other lookup
provider. A Sankaku post whose declared MD5 equals the query material MAY
support an exact-byte post candidate; artist tags, source URLs, and uploader
identity MUST NOT establish account identity or authorship.

#### Scenario: Verified MD5 finds a Sankaku post

- **WHEN** a Sankaku md5 lookup returns a post whose declared MD5 equals the
  locally verified seed occurrence MD5
- **THEN** the result may support an exact-byte post candidate while artist
  tags and uploader remain separate evidence

#### Scenario: Artist strategy on Sankaku is excluded

- **WHEN** a lookup plan requests an artist-name or alias strategy against
  Sankaku
- **THEN** planning excludes it with a stable reason and no Sankaku request
  is made

#### Scenario: Sankaku joins a crosscheck batch

- **WHEN** `catalog crosscheck` runs with the Sankaku provider lane over
  md5-bearing subjects
- **THEN** items execute under the batch's budgets and lane pacing with
  per-item outcomes recorded, and matches land as candidates exactly like
  the other md5 providers
