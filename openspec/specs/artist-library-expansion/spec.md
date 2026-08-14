## Purpose

Provide an explicit, bounded workflow for expanding the local catalog from a reviewed or selected
artist target while preserving target type, authorization provenance, and separation from user
activity, media acquisition, and identity conclusions.

## Requirements

### Requirement: Expansion targets are typed and stable
The system SHALL represent every expansion target as either a stable provider account or a stable
provider attribution entity. It MUST NOT treat an artist tag, uploader, mutable handle, display
name, alias, or free-text query as a provider account identity.

#### Scenario: Pixiv account is eligible
- **WHEN** a catalog account has a stable Pixiv native account ID and the adapter supports account-work enumeration
- **THEN** the system exposes it as an account expansion target with its provider, stable native ID, and supported operation

#### Scenario: Booru artist remains attribution
- **WHEN** a Danbooru-family artist record or artist tag can enumerate attributed posts
- **THEN** the system exposes an attribution expansion target and does not materialize or relabel it as an account

#### Scenario: Mutable or unstructured value is rejected
- **WHEN** a requested target is only a handle, display name, alias, uploader record, or arbitrary text
- **THEN** the system excludes it from direct expansion with a bounded reason and performs no network request

### Requirement: Target selection retains its authority and provenance
The system SHALL allow expansion from a target supported by a confirmed review decision or from an
explicitly selected stable catalog target. It MUST retain the seed, selection mode, selected target,
applicable decision or evidence reference, and an optional bounded user note without treating an
explicit selection as identity or authorship confirmation.

#### Scenario: Confirmed target uses review provenance
- **WHEN** the selected target is supported by a confirmed, current review decision
- **THEN** the expansion plan identifies that decision and the catalog entities that connect the seed to the target

#### Scenario: Explicit target does not create a review decision
- **WHEN** the user explicitly selects an otherwise eligible stable target without a confirmed relationship
- **THEN** the system records an explicit-selection provenance marker and does not create or alter an identity, authorship, source, or work review decision

#### Scenario: Ambiguous seed requires selection
- **WHEN** a seed resolves to multiple eligible expansion targets and none is selected explicitly
- **THEN** planning returns the bounded target choices and excludes execution until one target is selected

### Requirement: Expansion planning is offline, bounded, and deterministic
The system SHALL provide a read-only expansion plan before network execution. The plan MUST include
the selected target, provider capability, immutable request/page/record/time limits, retained count
or estimate provenance, exclusions, adapter and schema versions, a source revision, and a
deterministic plan digest. An unavailable retained estimate MUST be reported as unknown rather than
invented or obtained through implicit network access.

#### Scenario: Offline plan with retained estimate
- **WHEN** the catalog contains a current retained provider count for the selected target
- **THEN** planning reports the count, observation time, and source without contacting the provider or writing catalog state

#### Scenario: Offline plan with unknown estimate
- **WHEN** no retained count is available
- **THEN** planning reports an unknown estimate and still performs no network request or catalog write

#### Scenario: Unsupported target is explained
- **WHEN** the selected target type or provider lacks a compatible enumeration capability
- **THEN** planning returns an exclusion reason and no executable plan item

#### Scenario: Plan limits are finite
- **WHEN** a plan is requested with missing, zero, negative, or above-policy limits
- **THEN** the system applies documented finite defaults or rejects the invalid limits before any network request

### Requirement: Count probing is separate and explicit
The system SHALL treat a live provider count probe as a separate explicit network operation. A
probe MUST use an allowlisted adapter capability, immutable request/time limits, sanitized request
identity, raw-response retention, and typed provider outcomes. Probe results MUST be timestamped
provider observations and MUST NOT enumerate posts or download media.

#### Scenario: Supported count probe
- **WHEN** the user explicitly probes an eligible target whose provider declares count support
- **THEN** the system performs only the bounded count operation and retains the resulting count or typed failure

#### Scenario: Unsupported count probe
- **WHEN** the target provider does not declare a count capability
- **THEN** the system reports that the estimate remains unknown and makes no provider request

### Requirement: Expansion execution reuses bounded metadata synchronization
The system SHALL execute an accepted expansion plan through the existing adapter request gate,
raw-response retention, normalized page persistence, budget admission, checkpoint, and typed failure
contracts. It MUST reject a stale or altered plan before creating a provider request.

#### Scenario: Metadata-only enumeration succeeds
- **WHEN** an eligible current plan is executed
- **THEN** the system persists the discovered posts and any occurrence metadata supplied by the provider, associates those posts with the expansion target and underlying metadata run, and reports the committed limits, continuation state, and incomplete-detail count

#### Scenario: Stale plan is rejected
- **WHEN** the seed revision, target revision, capability, adapter version, schema version, or plan material differs from the accepted plan
- **THEN** execution creates no expansion run, metadata run, or provider request and reports a bounded stale-plan error

#### Scenario: Interrupted enumeration is resumable
- **WHEN** execution stops after one or more pages have committed
- **THEN** an explicit resume continues from the last compatible committed continuation without duplicating or skipping committed pages

### Requirement: Expansion does not silently broaden scope
The system MUST NOT recursively follow links, enumerate newly discovered accounts or attributions,
run candidate lookup, decide a review, download media, calculate similarity, select preferred
quality, or attach liked or bookmarked activity as a consequence of planning, probing, execution, or
resume.

#### Scenario: Newly discovered link remains inert
- **WHEN** an enumerated post contains another supported account or artist link
- **THEN** the link may be retained for later discovery but no new expansion is planned or executed automatically

#### Scenario: Discovered post has no user activity
- **WHEN** a post enters the catalog only through artist-library expansion
- **THEN** it has expansion and remote-observation provenance but no liked or bookmarked event unless independently imported from such a source

### Requirement: Expansion provides stable downstream handoffs
The system SHALL expose an offline expansion summary that identifies the discovered provider target,
underlying metadata run, stable discovered-post filter, available media-browse filter, eligible
occurrence selection references, and posts whose listing metadata lacks occurrences. It MUST NOT
infer target membership from names, tags, uploader roles, or source URLs, and MUST require a
separate explicit metadata-detail synchronization or acquisition operation where applicable.

#### Scenario: Browse only the expanded target
- **WHEN** an expansion has committed discovered works
- **THEN** its summary uses the durable expansion-to-post association to list only those works and any available occurrences without exposing private request material or raw payloads

#### Scenario: Listing metadata lacks occurrences
- **WHEN** a provider listing returns a post summary without media occurrence details
- **THEN** the expansion retains and reports the post as requiring explicit detail synchronization rather than inventing an occurrence or silently requesting one

#### Scenario: Selected occurrence feeds existing acquisition planning
- **WHEN** the user chooses one or more occurrence and variant references from expansion results
- **THEN** those references can be passed to the existing offline acquisition planner without creating a second download contract

### Requirement: Expansion history is durable, queryable, and redacted
The system SHALL provide bounded list and detail queries for plans, probes, executions, resumes,
targets, limits, counts, exclusions, outcomes, checkpoints, and downstream handoffs. Public and
human-readable output MUST omit credentials, cookies, authorization headers, signed URLs, raw
payloads, private paths, and private query material.

#### Scenario: Inspect completed and failed history offline
- **WHEN** the user lists or shows expansion history with network access disabled
- **THEN** the system returns deterministic bounded records for successful, paused, and failed work without modifying the catalog

#### Scenario: Sensitive provider data is retained privately
- **WHEN** an expansion response or request contains sensitive or private fields
- **THEN** durable private/raw storage may retain them under existing policy while normal expansion output exposes only allowlisted identifiers, digests, counts, states, and diagnostics

### Requirement: Stable e621 attribution can seed library expansion
Artist-library expansion SHALL allow a confirmed or explicitly selected stable e621 attribution
entity to enumerate posts through the versioned e621 artist-tag capability. It MUST preserve the
attribution target, exact provider tag identity, authority provenance, adapter/schema versions,
finite limits, and ID-keyset resume state without relabeling the attribution as an account.

#### Scenario: Explicit e621 attribution target
- **WHEN** a user selects a stable retained e621 artist attribution with a bounded note
- **THEN** offline planning produces an e621 attribution expansion choice and asserts no account identity or global authorship relationship

#### Scenario: Enumerated e621 posts enter the library workflow
- **WHEN** a current e621 expansion plan executes successfully
- **THEN** committed posts and occurrences are associated with that expansion and can be browsed and explicitly acquired without receiving liked or bookmarked activity

#### Scenario: Expansion resumes by post ID
- **WHEN** an e621 expansion pauses after committing a page
- **THEN** an explicit compatible resume uses the retained ID-keyset continuation without recursively expanding any discovered artist, alias, uploader, source, or account

### Requirement: e621 expansion estimates are evidence-bounded
The system SHALL report an exact retained e621 artist-tag `post_count` only when a current retained
tag observation unambiguously identifies the selected canonical artist tag. Arbitrary multi-tag or
filtered expansion counts SHALL remain unknown unless a later versioned provider capability proves
them; planning MUST NOT run a listing request merely to estimate size.

#### Scenario: Canonical artist tag has retained count
- **WHEN** the selected attribution maps unambiguously to a retained current artist-category tag with `post_count`
- **THEN** the offline plan reports that provider count, its observation time, source, and capability version

#### Scenario: Alias or filtered target lacks exact count
- **WHEN** the target depends on unresolved alias state, additional filters, or lacks a current exact tag observation
- **THEN** the plan reports an unknown estimate without network access
