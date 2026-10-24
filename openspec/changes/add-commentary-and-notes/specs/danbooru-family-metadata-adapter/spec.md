## ADDED REQUIREMENTS

### Requirement: Opt-in artist-commentary collection
The danbooru-family adapter SHALL support fetching artist commentary for one post by native
identifier via the provider's commentary endpoint under the bounded run contract, as an explicit
operator action separate from default post sync. Commentary observations SHALL retain the
provider-reported original and translated titles and descriptions, deduplicated by a digest over
the text facts so unchanged re-observation is idempotent and any text change lands as a new
observation. The operation SHALL require an already-retained post, SHALL retain the raw source
report with run and request provenance, and SHALL NOT alter post metadata or derive any tag,
relationship, or attribution conclusion from commentary text. A post with no commentary SHALL end
the run successfully with zero observations.

#### Scenario: An artist caption lands as one observation
- **WHEN** an operator enriches a retained post whose provider commentary carries an original
  title and description
- **THEN** one commentary observation is retained with both text fields and the raw report anchors
  it with provenance

#### Scenario: A commentary edit lands as a new observation
- **WHEN** the provider later reports different commentary text
- **THEN** a new observation is retained and the earlier one remains queryable

#### Scenario: No commentary is a successful empty observation set
- **WHEN** the provider reports no commentary for the post
- **THEN** the run ends successfully with no commentary observation and the raw report is retained

#### Scenario: Commentary never touches default sync
- **WHEN** default post synchronization runs
- **THEN** no commentary operation or observation occurs
