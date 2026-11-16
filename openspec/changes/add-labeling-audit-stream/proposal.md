## Proposal

### What

An audit sampling mode for the labeling system: `catalog label --audit N
[--seed S]` serves a deterministic random sample from the populations the
normal queue never asks about — auto-confirmed identical-md5 pairs, pairs
beyond the per-build queue cap, and random cross-artist negatives — plus a
calibration report (`catalog label-stats`) computing per-family verdict
rates with Wilson 95% intervals from the recorded labels.

### Why

Every pair label today comes from an enqueue signal, so population error
below the thresholds is unidentifiable: the auto-confirm rule rests on 59/59
seen positives, but its false-`same` rate in the unaskered space is bounded
only by assumption. Sampling the negative space and re-checking auto
decisions turns those assumptions into measurements; each audit pass
tightens the bound (bead `data-processing-4o3`, from the abstention-first
entity-resolution triage).

### Scope

- `build_audit_queue` in `labeling/queue.py` (three populations, seeded,
  deduped against existing labels, media-usable filter as usual).
- `labeling/calibration.py`: per-signal label counts, same/variant rate,
  Wilson 95% CI; `catalog label-stats <catalog> --json` report.
- Server/CLI wiring (`--audit`, `--seed`), tests, docs.
- Out of scope: changing enqueue thresholds or auto rules (the audit only
  measures), queue UI changes (audit pairs render identically).
