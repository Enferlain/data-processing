## Why

The lower half of the pipeline — review, metadata sync, browsing, acquisition — works, but the
user translates identifiers between commands by hand at every handoff: from a reviewed identity
to eligible expansion targets and their stable references, and from browsed occurrences to
acquisition selections (copying occurrence and variant identifiers out of `media list` output
into `assets download-plan --select` arguments). The expansion engine, the four-provider
capability registry (Pixiv account works, Danbooru and AIBooru artist tags, e621 artist tags),
and the expansion-scoped browse filter already exist; what is missing is the cohesive
target-anchored orchestration the roadmap names as the pipeline gap. This is kernel Phase C —
the first milestone built against the named provenance-kernel boundary.

## What Changes

- Extends reviewed-target resolution to report review state and eligibility: resolution from a
  confirmed identity's member accounts or an explicitly selected stable account or attribution
  already works offline today; what is added is per-candidate review-state reporting, with pending
  and rejected candidates reported as ineligible rather than silently omitted.
- Adds an offline capabilities view for a target: which enumeration operations apply, with
  provider, capability key and version, operation, and adapter/schema versions, plus explicit
  unsupported markers where a target kind has no capability.
- Adds expansion-plan-scoped acquisition planning: `assets download-plan` accepts a library
  expansion plan plus a fixed selection criteria set (variant, availability, eligibility, item
  limit) and resolves the occurrence selection from the expansion's committed associations
  offline — no hand-copied identifiers. Explicit occurrence-and-variant selection remains
  available.
- Completes provider-path proof where it is missing: the Pixiv path is already proven end-to-end
  with fixtures including pause and resume; this change adds Danbooru checkpoint/resume coverage,
  AIBooru execution and resume coverage, and a per-provider expansion matrix so every registered
  capability is proven through planning, execution, checkpoint, and resume.
- The workflow terminal remains a ready, immutable acquisition plan; downloads stay an explicit
  separate action. No second workflow engine, no new crawler, downloader, candidate ledger, or
  asset store; no recursive expansion; offline by default.

## Capabilities

### New Capabilities

- None. The workflow extends the existing expansion and acquisition capabilities rather than
  adding an umbrella spec.

### Modified Capabilities

- `artist-library-expansion`: adds reviewed-target resolution across platforms and the offline
  capabilities view; the existing provider-neutral requirements and the e621-specific
  requirements are unchanged.
- `remote-media-acquisition`: the selection grammar of explicit acquisition planning gains
  expansion-plan-scoped selection resolved from committed expansion associations; the existing
  explicit occurrence-and-variant selection, immutability, and network-explicitness requirements
  are preserved.

## Impact

- CLI: `catalog library` gains a capabilities subcommand and reviewed-target reference options on
  planning; `catalog assets download-plan` gains expansion-plan-scoped selection.
- Code: `media_catalog.library` (planning, service, queries) and the acquisition planning module;
  provider execution paths in `media_catalog.remote_sync`/adapters where fixture verification
  exposes gaps.
- No schema changes are expected — `library_expansion_plans` is parameterized by platform and
  capability, the acquisition plan tables by per-item provider request policy, and both are
  immutable; if a gap genuinely requires a migration it becomes a bounded one flagged in tasks.
- Documentation: the `catalog` tool guide gains the workflow walkthrough; changelog records the
  milestone.
- Tracking: Bead `data-processing-iso` (kernel Phase C).
