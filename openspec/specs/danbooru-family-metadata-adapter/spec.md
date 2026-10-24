## Purpose

Ingest metadata from Danbooru-compatible instances without conflating uploader accounts, community
artist attribution, source references, or provider-declared file identity.

## Requirements

### Requirement: Danbooru-family instances have independent platform identity
Each configured Danbooru-family instance SHALL have an explicit platform key, canonical base URL,
adapter compatibility declaration, credential reference, and request policy. Equal native IDs on
Danbooru and AIBooru SHALL NOT collide.

#### Scenario: Equal post IDs on two instances
- **WHEN** Danbooru and AIBooru each return post `123`
- **THEN** the catalog retains two posts under their independent platform identities

#### Scenario: Unsupported response shape
- **WHEN** a configured instance claims compatibility but returns an incompatible required shape
- **THEN** the raw response is retained and the run reports a malformed-response outcome rather
  than applying another instance's assumptions

### Requirement: Booru post metadata preserves provider fields and categories
The adapter SHALL retain post ID, canonical URL, creation and update times, rating, status and
availability flags, dimensions, file size, MIME or extension hints, original/sample/preview URLs,
source value, Pixiv ID when supplied, and tags separated into artist, character, copyright,
general, and meta categories. The adapter SHALL additionally retain engagement facts the
provider reports — score, up/down score components, and favorite count — and post status flags
(deleted, pending, flagged, banned) as post fact observations with raw provenance, and SHALL
retain media-asset variant dimensions (width, height, extension/MIME per variant, including
provider-native intermediate sizes) as variant metadata without changing which URL serves each
original/sample/preview role.

#### Scenario: Available post with categorized tags
- **WHEN** a post response contains all supported tag categories
- **THEN** each tag remains associated with the post under its provider category and spelling

#### Scenario: Deleted post retains identity
- **WHEN** a post is deleted or its media is unavailable but its metadata remains visible
- **THEN** the stable post and typed availability remain queryable without inventing file URLs

#### Scenario: Post reports engagement facts and status flags
- **WHEN** a post response supplies score, up/down scores, favorite count, and pending/flagged
  or banned state
- **THEN** the values persist as post metadata and flag observations tied to the retained raw
  observation, and repeated observations update them without duplicating rows

#### Scenario: Media asset reports variant dimensions
- **WHEN** a post response's media asset lists variants with widths, heights, and extensions
- **THEN** each variant's dimensions persist alongside its URL under its provider-native name,
  and the original/sample/preview roles keep their existing URL sources

### Requirement: Provider hashes remain declared assertions
An MD5 or other file hash supplied by a Danbooru-family provider SHALL be stored as a declared
occurrence assertion with provider provenance and SHALL NOT be exposed as locally verified unless
catalog-managed bytes independently verify it.

#### Scenario: Metadata-only post has an MD5
- **WHEN** a post response supplies an MD5 but no bytes are downloaded
- **THEN** the occurrence exposes the declared MD5 and has no verified asset MD5 association

#### Scenario: Later bytes disagree
- **WHEN** locally acquired bytes later produce a different MD5
- **THEN** the declared and verified values both remain visible as a mismatch

### Requirement: Uploader participation is distinct from artist attribution
When a provider supplies an uploader user ID, the adapter SHALL represent that stable platform
account as the post's uploader. Artist-category tags and booru artist records SHALL remain
community attribution entities and SHALL NOT be materialized as uploader, author, creator, or
cross-platform identity confirmation without separate evidence and review.

#### Scenario: Uploader and artist tag differ
- **WHEN** a post has uploader user `17` and artist tag `example_artist`
- **THEN** user `17` receives only the uploader role and the artist tag remains separate attribution

#### Scenario: Uploader metadata is absent
- **WHEN** the provider omits uploader identity
- **THEN** the post is stored without inventing an account participant

### Requirement: Booru artist records retain aliases and URLs
The adapter SHALL retain booru artist record IDs, names, other names, active/deleted state,
linked artist tags, observed external URLs, group name, banned state, and record creation and
update times as platform-scoped attribution metadata distinct from accounts and creator
identities.

#### Scenario: Artist has multiple external profiles
- **WHEN** an artist record lists Pixiv and X URLs under names that do not match the booru tag
- **THEN** all URLs and names remain associated with the artist observation for later discovery and
  evidence generation

#### Scenario: Artist record is deleted
- **WHEN** the provider marks an artist record deleted
- **THEN** its stable record, aliases, URLs, and deleted state remain queryable

#### Scenario: Artist reports group and ban state
- **WHEN** an artist record supplies a group name, banned state, or creation/update times
- **THEN** those facts persist on the attribution record with the observation's raw provenance

### Requirement: Source and Pixiv references are evidence, not conclusions
The adapter SHALL retain a post's source URL and provider `pixiv_id` as typed external references
with raw provenance. These references MAY generate reviewable match evidence but SHALL NOT
automatically confirm account ownership, creator attribution, post equivalence, or work identity.

#### Scenario: Source points to a Pixiv artwork
- **WHEN** a Danbooru post source resolves to a stable Pixiv artwork ID
- **THEN** the reference is queryable as cross-platform evidence without automatically merging the
  two posts or their accounts

### Requirement: Parent and child relations are directional and idempotent
The adapter SHALL retain provider parent and child post references as directional, platform-scoped
relations and SHALL update repeated observations without duplicating the same relation.

#### Scenario: Parent and children are returned together
- **WHEN** a post response identifies one parent and two children
- **THEN** the catalog retains the three correctly directed relations without labeling their visual
  variation type

### Requirement: Danbooru-family pagination is resumable and rate-aware
Listing operations SHALL preserve the provider continuation semantics, use keyset pagination when
supported, and obey the shared synchronization budgets and provider rate-limit state.

#### Scenario: Resume descending ID pagination
- **WHEN** a committed page yields a `b<ID>` continuation
- **THEN** a resumed run requests records after that boundary without reverting to an unbounded
  numeric page scan

#### Scenario: Rate-limit metadata is returned
- **WHEN** the instance supplies rate-limit headers
- **THEN** their non-secret state is retained and subsequent requests remain within the configured
  conservative policy and run budgets

### Requirement: Danbooru-family adapters declare lookup capabilities
Each supported instance SHALL declare whether it can look up posts by canonical source URL, embedded external post ID, and MD5, and whether it can search artist records by exact name, alias, or bounded text query. The caller MUST be able to reject an unsupported operation before a request, and instance-specific response shapes MUST remain isolated behind normalized results.

#### Scenario: Instance supports source but not artist text search
- **WHEN** capability inspection is requested for that instance
- **THEN** source lookup is eligible and artist text search is excluded without probing an undocumented endpoint

### Requirement: Reverse post lookup retains provider facts
Post lookup results SHALL retain the provider post identity, source values, embedded external identifiers, declared MD5, uploader identity, artist-tag attribution, availability, raw observation, and request provenance without converting declared values into verified facts.

#### Scenario: Look up by canonical X source URL
- **WHEN** the provider returns a post for an allowlisted canonical X status URL
- **THEN** normalization preserves the queried source, returned source fields, provider post ID, uploader, artist tags, and declared media facts as distinct evidence

#### Scenario: Look up by MD5
- **WHEN** the provider returns a post for an exact MD5 query
- **THEN** the MD5 remains provider-declared unless catalog bytes independently verify it

### Requirement: Artist lookup preserves attribution boundaries
Artist lookup SHALL retain exact names, aliases, other names, deprecation or replacement state, and external URLs. It SHALL NOT normalize an artist record or tag as an account, and an uploader SHALL remain separate from artist attribution.

#### Scenario: Artist record links to Pixiv
- **WHEN** an artist lookup result contains a Pixiv user URL and an unrelated uploader account
- **THEN** normalization retains the artist URL as reference evidence and the uploader separately, without confirming either as the X seed's identity

#### Scenario: Similar artist names
- **WHEN** a bounded text query returns multiple similarly named artist records
- **THEN** all retained results remain ordered weak leads with provider identities and no automatic winner

### Requirement: Pool collection is bounded, ordered, and evidence-only
The danbooru-family adapter SHALL support fetching a single pool by native identifier via the
provider's pool endpoint under the bounded run contract — declared budgets, a recorded remote
request, retained raw source report with provenance, and a typed outcome. Pool observations SHALL
retain the provider-declared membership order as an ordered list of member observations carrying
each member's native post identifier and position, with catalog post links only for posts already
retained. Re-observation of an unchanged pool (same membership, same order) SHALL be idempotent
through the observation digest; a changed membership or order SHALL land as a new retained
observation, never a rewrite. Pool observations SHALL NOT create works, relationships, or any
work-grouping conclusion — ordering is evidence for review-gated Phase D conclusions only.

#### Scenario: A pool fetch observes ordered membership
- **WHEN** an operator fetches pool 42 and the provider reports post_ids `[100, 7, 900]`
- **THEN** one pool observation is retained with three member observations at positions 1, 2, 3 in
  that order, each carrying its native post identifier, and the raw report anchors the observation

#### Scenario: Unretained members stay by native identifier
- **WHEN** a pool member's post is not yet retained in the catalog
- **THEN** the member observation retains its position and native identifier with no post link,
  and a later post sync may resolve it without rewriting the pool observation

#### Scenario: Unchanged pools re-observe idempotently
- **WHEN** the same pool is fetched again and membership plus order are unchanged
- **THEN** no new pool observation row is created while the fetch's raw report and run are still
  retained

#### Scenario: Reordered membership is a new observation
- **WHEN** a later fetch reports the same members in a different order
- **THEN** a new pool observation is retained and the earlier one remains queryable

#### Scenario: Pools claim no grouping conclusion
- **WHEN** pool observations are recorded
- **THEN** no work, relationship, or work-grouping conclusion is created automatically

#### Scenario: The single-pool endpoint does not paginate
- **WHEN** a pool fetch completes
- **THEN** it terminates after one request; resumable semantics apply only where a provider
  endpoint paginates, which this one does not

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
