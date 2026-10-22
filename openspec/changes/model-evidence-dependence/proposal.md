## Why

As cross-source relationships improve, the same claim repeats across mirrors (pixiv → danbooru → gelbooru → archives) and the same bytes arrive from five providers. Observation count is not independent-corroboration count: without an explicit notion of evidence dependence, future confidence or projection logic would over-count copied claims simply because they appear on several sources (gh#9).

## What Changes

- Classify the existing relationship vocabulary by its role in evidence dependence: **descent kinds** (reposts, derivatives, re-encodes, resizes, crops, censored variants, edits, transcodes, extractions, thumbnails), **equivalence kinds** (`same_bytes`, `same_work`), and **structural kinds** (`page_of`, `parent_of`) that anchor objects without expressing claim descent.
- Decide the lineage question: dependence is **derived from the relationship graph at read time**, not stamped onto rows. No lineage, group, or correlation identifier is added to evidence rows, observations, or objects; evidence rows stay single-finding facts and the relationship graph is the single lineage record.
- Add a lineage-derivation surface (`lineage_components`) in the relationships package: connected components over a stated dependence edge set (descent + equivalence kinds by default, restricted to conclusion-grade epistemic statuses and excluding rejected edges), joined through the structural anchoring of posts, occurrences, and work anchors. Read-only, deterministic, offline.
- Require corroboration surfaces to count lineages, not observations, under a stated dependence policy — counting observations as independent becomes an explicit stated choice, never a default.
- Record the design and a worked pixiv → danbooru → gelbooru → archive mirror-chain example in `docs/plans/evidence-dependence.md`, with the example's numbers produced by running the derivation, not hand-written.

## Capabilities

- **New Capabilities:** none.
- **Modified Capabilities:**
  - `provenance-kernel` — new requirement: corroboration counts lineages, not observations; dependence is graph-derived; independence assumptions are opt-in.
  - `work-relationships` — new requirement: dependence classification over the relationship vocabulary and the read-time lineage-derivation surface.

## Impact

- `src/media_catalog/relationships/dependence.py` (new): dependence vocabulary constants and `lineage_components`.
- `tests/test_evidence_dependence.py` (new): the mirror-chain, byte-equivalence, policy-filter, and read-only worked examples.
- `docs/plans/evidence-dependence.md` (new): decisions, rejected alternatives, worked example.
- No storage changes: no new tables, no new columns, no migrations. The derivation reads existing relationships, works, work representations, and occurrences.
- Follow-on (not in this change): as-of reconstruction over relationship conclusions (2ai follow-on) will let lineage derivation run under a cutoff; projections that count corroboration adopt the primitive when they exist.
