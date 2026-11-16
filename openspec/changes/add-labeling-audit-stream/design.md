# Design

## Decisions

- **Three audit populations, one per failure mode.** `audit_auto_same` — a
  random slice of `identical_md5` auto-labels (re-verify the 59/59 rule
  where it actually decided); `audit_beyond_queue` — same-artist and
  shared-signal pairs that exist but fall past the per-build `limit` (the
  queue's cap silently hides them); `audit_random_negative` — random
  available pairs sharing no artist (nothing suggests a relation; these
  bound false-enqueue thinking). Sample size splits evenly, remainder to
  auto re-verification.
- **Deterministic randomness** via `random.Random(seed)` with stable sort
  keys before sampling (post ids), so a re-run reproduces exactly and a new
  seed rotates. Default seed 0.
- **Verdicts flow through the ordinary path** — audit pairs are ordinary
  `PairCandidate`s with `audit_*` signals; the server UI, `record()`, and
  decision trail are untouched. Distinct signals keep audit labels
  separable from organic family labels in the calibration table (mixing
  them would double-count populations).
- **Wilson score interval** (95%) for the same-or-variant share per family —
  the standard small-sample binomial bound; computed in `calibration.py`
  from `pair_labels` grouped by signal. No approximation gymnastics: exact
  counts in, one interval out.
- **`label-stats` as a read-only report** in the maintenance family:
  per-signal rows plus a total; JSON-first like sibling commands.

## Risks

- Audit negatives with no visual relation may feel wasteful; the sample
  size is operator-chosen per invocation, and the point is the bound, not
  the fun.
- Auto-same re-verification labeling a pair `different` does not
  automatically unwind the auto rule — it becomes a calibration datapoint;
  rule changes stay an explicit operator decision.

## Migration Plan

None — no schema change; audit verdicts are ordinary pair labels.
