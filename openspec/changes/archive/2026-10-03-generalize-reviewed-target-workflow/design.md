## Context

The expansion engine, capability registry, and browse filter exist; the roadmap's pipeline gap is
the manual identifier translation between review, expansion, browsing, and acquisition planning.
`library_expansion_plans` is parameterized by platform and capability, the acquisition plan tables
by per-item provider request policy, and both are immutable; `catalog media list
--expansion-plan-id` already scopes browsing to a plan. See proposal.md for
why. This change is kernel Phase C and must satisfy the provenance-kernel spec's cross-cutting
invariants.

## Goals / Non-Goals

**Goals:**

- One cohesive offline path: reviewed anchor → eligible targets and capabilities → expansion plan
  → execution/resume → plan-scoped acquisition plan, with no hand-copied identifiers.
- Complete provider-path proof with fixtures, including checkpoint and resume: Pixiv is already
  proven end-to-end including pause and resume; this change adds Danbooru resume coverage, AIBooru
  execution and resume coverage, and a per-provider matrix. e621 already has the deepest coverage.

**Non-Goals:**

- No new tables, run families, candidate ledgers, downloaders, or capability specs.
- No downloads as part of the workflow — the terminal is an immutable acquisition plan; execution
  stays with the existing explicit download commands.
- No new providers (Gelbooru attribution enumeration waits for a concrete workflow); no fuzzy or
  query-language selection grammar — a fixed criteria set only.
- No changes to review semantics: resolution consumes confirmed decisions and explicit selections,
  never creates them.

## Decisions

### Generalize `catalog library` rather than add an umbrella surface

Chosen 2026-10-03. The `plan/probe/run/resume/runs/show` engine already implements the bounded,
checkpointed, audited contracts the workflow needs; a `catalog target` umbrella would be a second
orchestration layer beside it, and glue-only flags would remove friction without carrying state.
Rejected alternatives: new `target` verb family (second engine, spec overlap); thin
`--identity`-style flags on existing commands (no cohesive carry-through).

### Capabilities view and target resolution derive; they do not store

Both features are pure projections over the existing capability registry, the review ledger, and
the account/attribution tables — recomputed per invocation, offline, no new state. This keeps the
matrix honest against review changes (a reversed decision immediately removes eligibility) and
avoids a synchronization problem between stored and actual eligibility. Rejected: a cached
capabilities table (staleness vs the append-only review ledger for no measured cost win).

### Expansion-scoped selection resolves through committed associations

`download-plan --library-plan <id>` joins the plan's immutable
`library_expansion_posts` associations to occurrence/variant eligibility, applies the fixed
criteria set (variant, availability, eligibility, item limit), and feeds the existing immutable
acquisition-plan writer — the selection grammar widens, the plan contract does not. Posts flagged
`details_required` surface as exclusions with that reason rather than being skipped silently.
Rejected: a saved-selection table between browsing and planning (the plan already is the durable
artifact); a free-form filter language (fixed criteria only, per the milestone's own guardrail).

### Provider-path proof comes before CLI polish

The registry names four providers with uneven coverage today: e621 has the deepest proof
(pause/resume, matrix, estimates), Pixiv is proven end-to-end including `next_url` cursor
pause/resume, Danbooru has execution coverage but no checkpoint/resume tests, and AIBooru is
covered only at planning level. Tasks close exactly those gaps first — any provider-specific
drift is implemented inside the existing continuation contracts
(`continuation_adapter`/`version`, `transport_key`/`version`), not as new checkpoint shapes. If a
provider proves unimplementable within the contracts, the capability is reported unsupported for
that provider with a bounded reason rather than bending the contract.

### Workflow terminal is the acquisition plan

Downloads remain a separate explicit action (existing requirement: acquisition is explicit). The
workflow's last step hands the user a ready plan id and the exact command to execute it. Rejected:
chaining into `assets download` under a `--network` flag (collapses two explicitly separate
network decisions into one).

## Risks / Trade-offs

- [Pixiv or AIBooru execution reveals contract drift mid-milestone] → Fixture-first task ordering
  surfaces drift before CLI work; the fallback is reporting the capability unsupported with a
  bounded reason, never bending the run contract.
- [Selection criteria creep into a query language] → Fixed criteria set in the spec; anything
  richer is explicitly out of scope and deferred.
- [Capabilities view and review state disagree] → Derivation-only design removes the stored copy;
  tests pin resolution against confirmed, reversed, and pending review states.
- [Large expansions make plan-scoped selections unwieldy] → Item limits and by-limit exclusion
  reporting are part of the selection contract from the start.

## Migration Plan

No schema changes expected. If fixture verification exposes a gap that genuinely requires one, it
becomes a separate bounded migration inside this change with its own tests — flagged in tasks, not
assumed. Rollback is reverting code; no data is transformed.

## Open Questions

- Whether Gelbooru attribution enumeration should register a capability later — deferred until a
  concrete workflow needs it (same rule as new providers).
- Whether the capabilities view grows per-operation depth (for example, supported sort orders per
  provider) — deferred until a user need appears; the fixed criteria decision covers the present
  scope.
