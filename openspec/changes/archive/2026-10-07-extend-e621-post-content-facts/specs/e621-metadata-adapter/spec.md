## MODIFIED Requirements

### Requirement: e621 posts retain nested provider facts
The system SHALL normalize stable post identity; created and updated times; original file, sample,
and preview metadata; declared MD5, extension, byte size, and dimensions; categorized tags;
sources; rating; score; uploader; pools; relationships; counts; description presence and content
(as post text — e621 descriptions embed the artist's original source-post caption); file duration
(as the occurrence's millisecond column); alternate sample representations (under `alternate:*`
variant names with dimensions, extension/MIME, fps, and codec); and provider
flags while retaining the complete raw response. Provider-declared hashes MUST remain distinct from
locally verified hashes.

#### Scenario: Normal post exposes three representations
- **WHEN** a post response contains original, sample, and preview objects
- **THEN** the catalog retains one ordered media occurrence with named variants, preserves which exact facts describe the original, and makes no request to any media URL

#### Scenario: Dynamic tag categories
- **WHEN** the provider returns tag arrays such as artist, character, copyright, species, lore, meta, contributor, invalid, or a future category
- **THEN** known categories retain their neutral mapping and unknown categories remain recoverable from raw data without being silently reassigned

#### Scenario: Post relationships
- **WHEN** a post declares a parent, children, pools, or sources
- **THEN** the catalog retains directed provider relationships and source references without treating them as same-work, authorship, or account-identity conclusions

#### Scenario: Description embeds the source caption
- **WHEN** a post's description carries the artist's original source-post text
- **THEN** the content persists as the post's text with its raw provenance, and the presence flag remains derivable

#### Scenario: Video duration and alternate representations
- **WHEN** a post reports a top-level duration and URL-bearing sample alternates
- **THEN** the occurrence carries the duration in milliseconds and the alternates appear under `alternate:*` variant names with their technical metadata, without altering the original/sample/preview roles
