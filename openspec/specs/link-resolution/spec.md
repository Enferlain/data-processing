# link-resolution Specification

## Purpose
TBD - created by archiving change add-link-driven-ingest. Update Purpose after archive.

## Requirements

### Requirement: Supported-site URLs resolve offline to fetch targets
The system SHALL resolve a post URL from any registered platform to its platform
key, fetch operation, and adapter target by parsing alone — no network access and
no catalog state. Resolution SHALL accept the canonical URL form each platform's
normalizer emits plus the common pasted variants (`www.`/`en/`/`.json` forms,
equivalent family hosts, legacy query forms). Unsupported hosts, non-HTTPS
schemes, and malformed identifiers SHALL fail with an actionable message before
any request is made.

#### Scenario: Canonical URL round-trips
- **WHEN** a URL is resolved that a platform's normalizer itself would emit
- **THEN** the resolution reports that platform, the fetch-post operation, the
  adapter target, and the same canonical URL

#### Scenario: Unsupported link
- **WHEN** a URL's host is claimed by no registered platform
- **THEN** resolution fails naming the host without contacting it

### Requirement: Fetch composes resolution with the platform's real sync path
The fetch command SHALL sync a resolved link through the same adapter
construction, credential resolution, pacing floors, and budget limits as the
platform's dedicated metadata command, and SHALL support stopping after
resolution without opening the catalog. Its report SHALL name the resolved
platform, target, canonical URL, and the sync result.

#### Scenario: Link-driven fetch
- **WHEN** an operator fetches a supported post URL against a catalog
- **THEN** the metadata sync runs for the resolved platform and target and the
  run result is reported

#### Scenario: Resolve only
- **WHEN** the command runs with resolve-only
- **THEN** it reports the resolution and performs no catalog or network access
