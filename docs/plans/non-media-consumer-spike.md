# Second-consumer spike: a non-media intake through the kernel

Status: executed (2026-10-23; Bead `data-processing-vyc`, GitHub issue #4)
Artifacts: `scripts/package-watchlist-spike/` (fetch → intake → project), real PyPI fixtures captured
under budgets, findings and follow-up beads below. Spike code stays in `scripts/` — no product surface.

The spike is one deliberately small non-media intake: watch **Python package metadata** from the public
PyPI JSON API (stable identifiers, no auth, small documents). A bounded live fetch captured three real
package documents (`six`, `tomli`, `imagehash` — 40–400 KB each) under declared item/byte/time budgets;
the rest runs offline. It exercises all six requested areas: source identity, append-only source
reports, bounded runs, typed normalization, evidence attachment, and one rebuildable as-of projection.

## What was executed

```text
fetch.py   → 3 real PyPI documents captured; budgets honored; typed-outcome vocabulary in the manifest
intake.py  → source 'pypi' registered; 3 raw reports stored; 3 package records + append-only
             observations; 3 evidence rows through the shared ledger; bounded run with
             storage-immutable inputs; one labeled simulated later observation for 'six'
project.py → rebuildable package-facts projection: newest-observation-wins per field, all history
             retained, as-of cutoff, spec digest (reusing the kernel projection machinery verbatim)
```

Current projection from a single-intake catalog (newest wins — the labeled later observation for
`six` resolves as 1.18.0 yanked; a re-intaken catalog shows the same rows plus the F4-side effects
discussed below):

```json
{"package":"imagehash","latest_version":"4.3.2","yanked_latest":false,"observation_count":1, ...}
{"package":"six","latest_version":"1.18.0","yanked_latest":true,"observation_count":2, ...}
{"package":"tomli","latest_version":"2.5.0","yanked_latest":false,"observation_count":1, ...}
```

Under `--as-of 2026-10-23T05:30:00Z` (between the two `six` observations), `six` reconstructs as
`1.17.0`/not-yanked with its real evidence pointer, and the spec digest changes — the cutoff
participates in the recipe, exactly as `add-as-of-semantics` specifies.

Storage-enforced immutability in spike-owned tables (same trigger idioms as kernel migrations) was
verified by attempted violations:

```text
blocked: spike_packages rows are immutable
blocked: spike_package_observations are append-only
blocked: spike run inputs are immutable
run state advance: accepted
```

## The five questions

### 1. Which kernel contracts work unchanged?

- **Source identity** — `platforms` accepted `pypi` (key pattern, display name, base URL) with the
  adapter columns simply unused. No obstacle.
- **Append-only source reports** — `raw_payloads` content addressing deduplicated repeated intakes
  (three payloads across two intake runs), and `store_raw`'s record validation (platform pattern,
  transport pair, timestamp normalization) is domain-neutral. One caveat below (F4).
- **Evidence ledger** — `match_evidence` accepted non-media evidence (a name-normalization detector)
  through the writer's generic insert, deduplicated by digest. The stance/kind/strength vocabulary
  fits. Only the method *name* (`insert_relationship_evidence_row`) is relationship-flavored.
- **Projection machinery** — `ProjectionSpec`, the six policy slots, canonical digests, and as-of
  cutoff participation were reused verbatim. `preferred_representation: not_applicable` shows the
  one media-flavored slot is honestly nullable in meaning.
- **Temporal semantics** — the as-of rule (observation time ≤ cutoff, re-resolve newest-wins) and the
  parsed-comparison lesson (`julianday(replace(...))`, not lexicographic) transferred one-to-one.

### 2. Which APIs still assume post/account/media semantics?

- **Run operation vocabulary (F2)** — `REMOTE_OPERATIONS` is closed and media-shaped
  (`fetch_post`, `fetch_account`, `list_account_posts`, `fetch_attribution`, `fetch_tag`,
  `fetch_tag_alias`). `fetch_package` is refused: `unsupported remote operation: fetch_package`.
  Worse, the control probe shows `fetch_tag` on a `pypi` run is *accepted* — bending is possible and
  nothing but honesty guards it.
- **Relationship endpoints (F3)** — `ENDPOINT_KINDS` is closed to `work`/`media_occurrence`/`post`/
  `asset`; a package cannot join the relationship graph: `relationship endpoints must name a known
  object kind`. Evidence attachment survives (the ledger is generic), typed linking does not.
- **Outcome vocabulary is neutral** — `REMOTE_OUTCOMES` and `BUDGET_BOUNDARIES` were reused verbatim
  in the spike run table's CHECK constraint; no media residue.

### 3. Does `platforms` need a source-kind generalization?

**No schema change now.** A remote API source fits the current row; "platform" is social-flavored
naming, not coupling. A `source_kind` becomes worth adding only when a *local* (non-remote) source
lands and needs different lifecycle semantics (no instance host, no credentials, offline runs). The
real gap the spike found is not source identity but observation anchoring (F4).

### 4. Is the run contract reusable outside remote metadata/media acquisition?

The contract's **shape** transferred cleanly: declared item/byte/time budgets, counters, typed
outcome, budget boundary, immutable inputs — mirrored in `spike_runs` with kernel outcome vocabulary,
and storage-enforced input immutability worked on the first attempt. The **tables** are not reusable:
`remote_runs` requires a media operation value and remote-shaped columns, so a non-media consumer
either extends the kernel vocabulary or mirrors the contract, as this spike did. Additionally:

- **F4 — anchorless observation identity**: `store_raw` dedups observations on
  `(import_run_id, object_kind, native_id, raw_payload_id)`. With no run/request anchor the key is
  all-NULL on that column, SQLite treats NULLs as distinct, and **re-intake of identical payloads
  duplicates observation rows** (3 → 6 in the experiment) even though payloads dedup. Media adapters
  never hit this because every observation anchors to a request or import run; the kernel implicitly
  assumes anchoring. The split outcome in the experiment is instructive: the anchored rows stayed
  deduped only because the anchorless lookup returns the *earliest* matching observation (so the
  second intake reused ids 1–3), while the spike's own anchorless simulated row — no raw pointer,
  NULL in the uniqueness key — duplicated exactly the same way (4 → 5 rows before the spike made
  that insert idempotent). One mechanism, two symptoms, both rooted in NULL-distinctness.

### 5. Which abstractions must NOT move into the kernel?

- **Typed domain records** — package observations are family tables with family fields. The kernel
  should keep supplying the *pattern* (append-only observations, immutability tiers, newest-wins
  projection policy), never a generic EAV/entity bucket. This matches the issue's non-goal.
- **Works/relationship endpoint kinds** stay media until a non-media family actually needs typed
  linking; then extend `ENDPOINT_KINDS` by vocabulary addition (like `page_of`/`parent_of` were
  added), not by a generic "object" endpoint.
- **Candidate/matching machinery** — post/account-shaped by design; untouched by this spike.

## Verdict table

| Kernel surface | Reused unchanged | Coupling found |
| --- | --- | --- |
| `platforms` source identity | yes | naming only |
| `raw_payloads` content addressing | yes | — |
| `raw_observations` via `store_raw` | yes, with caveat | anchorless intakes duplicate rows (F4) |
| `match_evidence` ledger | yes | method naming is relationship-flavored |
| Run contract (shape, outcomes, budgets) | yes, mirrored | operation vocabulary is media-closed (F2) |
| Relationship model | no | endpoint kinds are media-closed (F3) |
| Projection spec/digests/as-of | yes, verbatim | — |
| Immutability trigger idioms | yes, verbatim | — |

## Follow-up beads filed

- `data-processing-6y1` — run-operation vocabulary: open per-source operations or keep the closed
  media set (kernel decision; unblocks non-media runs without bending) — **F2**
- `data-processing-40x` — anchorless raw-observation identity: require an anchoring run in
  `store_raw` or extend the identity key so anchorless re-intake dedups — **F4**
- `data-processing-9h6` — relationship endpoint-kind generalization decision, deferred until a
  non-media family needs typed linking — **F3**
