## MODIFIED Requirements

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
