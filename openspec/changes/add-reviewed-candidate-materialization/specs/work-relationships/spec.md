## ADDED Requirements

### Requirement: Confirmed candidates materialize into relationships on operator command
The system SHALL provide an explicit materialization operation that converts confirmed post
match candidates into relationship rows. Materialization SHALL accept only candidates whose
current review state is confirmed, SHALL map the candidate's relation kind onto the
relationship vocabulary with a stated fixed mapping (`sourced_from` and `repost_of` to
`reposted_from` between the posts; `same_work`, `variant_of`, and `derived_from` between the
posts' work anchors), SHALL attach the candidate's entire evidence bundle through the
relationship-evidence join, and SHALL record a review decision naming the candidate as the
materialization source. Materialization SHALL be idempotent, SHALL NOT modify the candidate
or its ledger, and SHALL NOT require or perform any network access. Nothing except this
operator command SHALL create relationships from candidates — matchers, lookups, and
unconfirmed candidates never materialize.

#### Scenario: A confirmed candidate becomes one reviewed relationship
- **WHEN** an operator materializes a confirmed post candidate whose target is a catalog
  post
- **THEN** exactly one relationship exists with `reviewed` epistemic status and confirmed
  review state, the candidate's evidence rows are attached to it, a review decision names
  the candidate as the source, and the candidate's own state and ledger are unchanged

#### Scenario: Re-materialization attaches nothing new
- **WHEN** the same confirmed candidate is materialized again
- **THEN** no duplicate relationship, decision, or evidence link is created

#### Scenario: Unmaterializable candidates are refused with reasons
- **WHEN** materialization encounters a candidate that is pending or rejected, has relation
  kind `unresolved`, has a target reference that resolves to no catalog post, or (for a
  work-level kind) has a post without a materialized work anchor
- **THEN** that candidate is reported with a typed refusal reason, no relationship is
  created for it, and other candidates still materialize
