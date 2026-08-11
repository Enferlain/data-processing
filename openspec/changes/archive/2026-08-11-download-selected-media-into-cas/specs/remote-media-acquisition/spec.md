## Purpose

Defines explicit, bounded, resumable acquisition of selected remote media into verified content-addressed storage while preserving source provenance and operational evidence.

## ADDED Requirements

### Requirement: Acquisition is explicit and selection-scoped
The system SHALL acquire remote bytes only through an explicit acquisition operation over selected catalog media occurrences or their named variants. Metadata synchronization, discovery, import, and read-only query operations MUST NOT trigger media downloads.

#### Scenario: Plan selected occurrences without network activity
- **WHEN** a user plans acquisition for a bounded set of occurrence identifiers
- **THEN** the system reports the eligible variants, exclusions, estimated known sizes, and applicable limits without issuing media requests or changing managed storage

#### Scenario: Metadata synchronization remains metadata-only
- **WHEN** remote metadata synchronization creates or updates an occurrence with downloadable URLs
- **THEN** the system persists the metadata without fetching those URLs or creating an acquisition run

### Requirement: Plans resolve stable catalog targets
An acquisition plan SHALL identify every target by stable catalog identifiers and SHALL record the selected remote variant, request-policy identity, and relevant source observation. Execution MUST reject targets whose material acquisition inputs changed after planning unless the user creates or explicitly refreshes the plan.

#### Scenario: Stale planned target is rejected
- **WHEN** an occurrence's selected URL, variant identity, or provider request policy changes after a plan is created
- **THEN** execution records a stale-target outcome without requesting the superseded target

#### Scenario: Already linked content is excluded
- **WHEN** a selected occurrence is already linked to an asset satisfying the same verified source claim
- **THEN** planning marks the item as already satisfied and execution does not download it again

### Requirement: Acquisition work is bounded and durable
The system SHALL persist acquisition runs, items, and individual attempts with durable states and SHALL enforce configured limits for item count, response bytes, total run bytes, attempt count, elapsed time, and concurrency. An interrupted run MUST remain inspectable and eligible items MUST be safely resumable or retryable.

#### Scenario: Run byte budget is reached
- **WHEN** completing another response would exceed the run's configured byte budget
- **THEN** the system stops starting new transfers, preserves completed results and safe partial state, and records a budget-exhausted outcome

#### Scenario: Process interruption leaves durable state
- **WHEN** the process stops after an attempt begins but before the item reaches a terminal state
- **THEN** a later inspection identifies the interrupted attempt and the item can be resumed or restarted according to its validated transfer state

#### Scenario: Repeated execution is idempotent
- **WHEN** the same completed plan or run is executed again
- **THEN** the system does not duplicate assets, occurrence links, completed attempts, or published CAS bytes

### Requirement: Provider request policies are explicit and secret-safe
Every transfer SHALL use a versioned provider request policy that defines allowed schemes, source hosts, redirect hosts, required non-secret headers, authorization behavior, and retry classification. The system MUST validate every redirect hop and MUST NOT persist credentials, bearer tokens, cookies, signed query values, or other configured secrets in plans, database records, logs, or user-facing reports.

#### Scenario: Pixiv media request uses its provider policy
- **WHEN** a selected Pixiv occurrence requires a provider-specific referer or authorization recipe
- **THEN** the transfer applies the current Pixiv policy at request time while the persisted item contains only the policy identity and redacted source information

#### Scenario: Redirect leaves the allowlist
- **WHEN** a media response redirects to a scheme or host not allowed by the selected provider policy
- **THEN** the system stops before requesting the disallowed target and records a non-retryable policy failure

#### Scenario: Failure output is redacted
- **WHEN** a request containing credentials or a signed URL fails
- **THEN** persisted and displayed failure evidence identifies the source safely without exposing secret headers or sensitive query values

### Requirement: Partial transfers are resumed only with remote validation
The system SHALL retain bounded partial-transfer state for retryable interruptions. It MUST resume with a byte range only when the remote representation can be validated against recorded response validators and the server honors the requested range; otherwise it SHALL discard or quarantine the unsafe partial and restart from byte zero.

#### Scenario: Validated range resume succeeds
- **WHEN** a partial transfer has a strong validator and the server returns a matching partial response for the expected byte offset
- **THEN** the system appends the response and verifies the complete byte stream before publication

#### Scenario: Validator changes during resume
- **WHEN** the server's validator or returned content range does not match the recorded partial state
- **THEN** the system does not combine the representations and restarts or records a source-changed outcome

#### Scenario: Server ignores the range request
- **WHEN** a resume request receives a full response instead of a valid partial response
- **THEN** the system replaces the partial transfer from byte zero rather than appending the full response

### Requirement: Remote bytes pass bounded staging and inspection
The system SHALL stream responses into catalog-owned staging while enforcing response-size and inspection limits. It SHALL compute verified SHA-256 and MD5 digests and SHALL detect MIME type, dimensions, frame count, and the configured perceptual fingerprint when supported. Unsupported but otherwise permitted media MAY be retained as exact-only assets with an explicit inspection classification.

#### Scenario: Response exceeds its byte limit
- **WHEN** headers or streamed bytes exceed the configured item limit
- **THEN** the transfer stops, no asset is published, and bounded failure evidence is retained

#### Scenario: Supported image is inspected
- **WHEN** a complete supported image passes staging and inspection
- **THEN** its verified exact hashes and detected media properties are available before CAS publication

#### Scenario: Permitted media cannot be perceptually inspected
- **WHEN** a complete permitted file type cannot produce a configured perceptual fingerprint
- **THEN** the system may publish it as exact-only while recording the inspection limitation

### Requirement: Declared and verified claims remain distinguishable
Provider-declared hashes, sizes, MIME types, and dimensions SHALL remain source assertions with provenance and MUST NOT be overwritten by locally verified values. The system SHALL compare compatible declared and verified claims and SHALL classify mismatches before linking the asset as a successful acquisition.

#### Scenario: Provider MD5 matches verified bytes
- **WHEN** a provider-declared MD5 equals the locally computed MD5
- **THEN** both the declared assertion and verified fingerprint remain queryable and the item records a matched verification result

#### Scenario: Provider hash does not match
- **WHEN** a compatible provider-declared exact hash differs from the locally computed value
- **THEN** the system preserves both values, does not report the acquisition as successfully verified, and quarantines the staged content or records equivalent retained evidence according to policy

### Requirement: Publication uses the managed CAS contract
Only complete, policy-compliant, verified staged content SHALL be published into managed content-addressed storage. Publication SHALL preserve the existing immutable SHA-256 layout, collision and integrity checks, root locking, durable directory synchronization, and descriptor-relative path protections.

#### Scenario: Identical bytes already exist
- **WHEN** verified downloaded bytes have a SHA-256 already present and valid in the CAS
- **THEN** the system reuses the existing asset and location without replacing or duplicating the stored bytes

#### Scenario: Existing CAS target is inconsistent
- **WHEN** the expected CAS target exists but fails identity or byte verification
- **THEN** publication fails closed and the occurrence is not linked to the inconsistent target

### Requirement: Successful acquisitions preserve provenance and link idempotently
After durable CAS publication, the system SHALL upsert the verified asset, managed location, fingerprints, source provenance, and occurrence-to-asset association in a recoverable transaction. Reconciliation MUST repair a publication that succeeded before a database interruption without redownloading valid bytes.

#### Scenario: Publication succeeds before database interruption
- **WHEN** CAS publication completes but database persistence is interrupted
- **THEN** a later retry recognizes the valid CAS object and completes the catalog records without downloading the media again

#### Scenario: Occurrence already links to the asset
- **WHEN** persistence repeats for an existing occurrence and verified asset association
- **THEN** the association remains singular while new attempt provenance can still be inspected

### Requirement: Operators can inspect and retry acquisition outcomes
The CLI and query API SHALL expose redacted plans, run summaries, per-item states, bounded attempt evidence, current retry eligibility, and links to resulting catalog asset identifiers. Users SHALL be able to retry eligible failed or interrupted items without including successful or non-retryable items unless explicitly requested.

#### Scenario: Inspect a mixed-outcome run
- **WHEN** a run contains completed, quarantined, policy-failed, interrupted, and budget-deferred items
- **THEN** its summary reports deterministic counts and each item exposes its outcome and safe next action

#### Scenario: Retry eligible failures
- **WHEN** a user retries a run using the default retry selection
- **THEN** only retryable failed or interrupted items are attempted and prior attempt evidence remains unchanged

### Requirement: External download tools cannot bypass verification
Files or URLs supplied by an optional external downloader bridge SHALL enter through a documented import or staging boundary and MUST satisfy the same limits, verification, provenance, quarantine, CAS publication, and idempotent linking requirements as native transfers.

#### Scenario: gallery-dl-produced file is imported
- **WHEN** a future gallery-dl bridge supplies a completed file for a selected occurrence
- **THEN** the catalog treats the file as unverified input and does not link it until the normal verification and publication contract succeeds
