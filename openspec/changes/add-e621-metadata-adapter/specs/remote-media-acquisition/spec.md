## ADDED Requirements

### Requirement: e621 media acquisition uses a dedicated provider policy
Explicit acquisition of e621 occurrences SHALL use a versioned e621 request policy that accepts
only returned HTTPS original, sample, or preview URLs on verified provider media hosts, sends the
required descriptive User-Agent and referer if applicable, validates every redirect before
following it, and preserves declared original-file claims only for the original variant.

#### Scenario: Download returned original
- **WHEN** an acquisition plan selects an available e621 original variant
- **THEN** the request uses the e621 policy, verifies bytes through the existing staging and CAS flow, and compares the resulting MD5, size, MIME type, and dimensions with original-file claims where available

#### Scenario: Download sample or preview
- **WHEN** a sample or preview variant is selected
- **THEN** the system records locally verified facts for that representation without applying the original file's declared MD5 or size to it

#### Scenario: Returned URL is absent or host is not allowlisted
- **WHEN** the selected variant has a null URL or its destination or redirect leaves the installed e621 host policy
- **THEN** planning or execution fails before requesting the untrusted destination and records a bounded policy outcome

#### Scenario: Metadata synchronization stays media-free
- **WHEN** e621 metadata exposes original, sample, and preview URLs
- **THEN** no media request occurs until the user separately creates and executes an acquisition plan
