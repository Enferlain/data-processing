## Why

Migration 0012's review identified audit surfaces still protected only partially or by
convention (Bead `data-processing-5de`): six pre-0012 update-only surfaces permit deletion,
`media_acquisition_verifications` rows have no trigger at all, and `raw_payloads` is protected
only transitively through the observations that reference it. The kernel spec states these
weaker strengths accurately today; this change removes the need for the caveat.

## What Changes

- One additive migration (0013) adds: no-delete triggers for `library_expansion_plans`,
  `library_expansion_probes`, `library_expansion_executions`, `library_expansion_posts`,
  `candidate_lookup_requests`, and `media_acquisition_attempts` (their existing
  update triggers are untouched — terminal-conditional for requests and attempts,
  unconditional for the expansion surfaces); no-update and no-delete triggers for
  `media_acquisition_verifications` and `raw_payloads` (both confirmed plain-insert only by the
  mutation sweep); and primary-key guards backported to the 0006/0007 immutable-inputs triggers
  by drop-and-recreate, matching 0012's stronger pattern.
- The provenance-kernel spec's audit-immutability requirement is updated: the fully-immutable
  enumeration gains acquisition verification records and source-report payloads; the
  update-rejected surfaces become undeletable; the deletion scenario widens accordingly.
- No data changes, no table rebuilds, and no code changes — the sweep found zero delete
  statements on every guarded surface.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `provenance-kernel`: the "Storage-enforced audit immutability" requirement's enumeration and
  deletion scenario are extended as above. No other requirement changes.

## Impact

- New migration `src/media_catalog/migrations/0013_audit_immutability_completion.sql` with twelve triggers (ten new plus two recreations).
- Focused tests extend `tests/test_kernel_storage_enforcement.py`.
- Tracking: Bead `data-processing-5de`.
