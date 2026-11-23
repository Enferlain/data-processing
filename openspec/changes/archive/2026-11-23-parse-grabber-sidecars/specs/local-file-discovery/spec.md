## ADDED requirements

### Requirement: Folder ingest retains parsed sidecar tags as seed evidence

Folder ingest SHALL parse same-basename `.txt` sidecars next to media files
and retain each as a categorized raw observation attached to its file seed
under an idempotent per-folder import run. Sidecar-derived facts SHALL NOT
write the provider tag tables, create posts, or assert relationships.
Sidecars without a media twin SHALL be counted without being opened, and
re-ingesting a folder SHALL duplicate nothing.

#### Scenario: sidecar lands on its seed

- **WHEN** `image.png` materializes and `image.png.txt` carries
  `artist:someone, 1girl`
- **THEN** one raw observation holds the parsed tags with categories
  (artist/general) keyed to that seed, and `post_tags` stays empty

#### Scenario: pool metatag is counted

- **WHEN** a sidecar line contains `pool:12345`
- **THEN** ingest reports it in the pool-tag count and retains it in the
  payload, without creating pool observations

#### Scenario: orphan sidecar is skipped

- **WHEN** a `.txt` file has no media twin in the directory
- **THEN** it is counted as orphan and its content is never read

#### Scenario: re-ingest is a no-op

- **WHEN** the same folder is ingested again
- **THEN** seeds are existing, the sidecar import run is reused, and the
  raw observation count does not grow
