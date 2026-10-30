# Togeari architectural investigation (research note)

Status: investigated 2026-10-30 (Bead `data-processing-164`), from the local clone
(`~/Projects/sd-scripts-resources/Togeari`, togeari 0.3.0) and its consumption by KohakuGBC.
Investigation only; no adoption decision, no code change.

## What Togeari is

An out-of-order dataflow machine for KIR jobs, built exactly like an OoO CPU core
(README "Concepts"; `src/togeari-rust/{lanes,program,runtime,contracts}`):

- A KIR program describes one job as plain sequential code (calls, branches, loops).
  Togeari runs thousands of jobs concurrently, overlapping everything the sequential
  semantics cannot distinguish — inside a job (run-ahead past undecided branches, `parallel`,
  `each` strands) and across jobs (batching calls of one kind onto shared engine units).
- Register renaming (value slots), a reorder buffer (per-job window retiring in program
  order), and precise exceptions (faults taken at retire; younger work squashed; `@try`)
  make concurrent runs *exactly* equal to the sequential reference — provable, because the
  conformance recorder keeps every call in retire order and replays it through the
  kohakunode reference interpreter (`docs/guides/conformance.md`, `togeari conform`).
- Lanes sit in front of interchangeable engine units (one lane per engine kind): they queue
  ready calls from every job, form batches, pick units by policy, multi-issue, retry, fail
  over, and hot-swap units. Engines are a tested contract (B1–B7: non-blocking submit,
  exactly one result per item, honest capacity, item-vs-unit error separation;
  `check_engine`, `togeari units`). Builtins: `PythonCallEngine` (threads/processes),
  `WebCallEngine` (HTTP), `TorchEngine` (models sharing devices under one scheduler).
- Dual dispatcher core: a Python reference and a Rust core (`togeari._rs`, shipped in every
  wheel, 1.9–5.1× faster) that make the same decisions in the same order. One machine is one
  process with one dispatcher thread — explicitly not a cluster manager or long-lived-task
  workflow scheduler.

## Integration surface, footprint, maturity

- Host API: build a `Machine` from programs + a node library + lane/engine configuration;
  sources and sinks are pluggable (`togeari.io`); plugins cover admission, submit, results,
  faults, budgets, tracing, the inspector. KohakuGBC's `build(config-layers)` is a thin
  configuration-driven wrapper over this.
- Footprint: core is light (`kohakunode>=0.3.0`; optional extras `web`, `torch`, `vault`,
  `report`). The Rust extension ships in wheels for CPython 3.11–3.14 across platforms;
  source builds need a Rust toolchain.
- Maturity: 145 test files; thorough docs/guides (checkpoints, execution-policy,
  execution-identity, committed-events, conformance); Apache-2.0; version 0.3.0 — young and
  evolving with its first real consumer (KohakuGBC), so API churn is the honest expectation.

## Engineering-idea attribution (correcting the bead)

The ideas the bead named — paged KV caching, CUDA graphs, prefix snapshots, Triton kernels —
do **not** live in Togeari. They are KohakuvLLM (the vLLM plugin) and
`kohakugbc_models/qwen35` territory. What Togeari itself is worth mining for: the lane
batching/multi-issue engine contract, precise-fault ordering under concurrency, the
dual-reference-core discipline (identical decision order, replay-verified), and the
plugin-at-every-seam inspection model.

## Verdict for data-processing

- **Where it would fit:** a future enrichment lane orchestrating per-item multi-model jobs
  (caption/detect/embed with divergent per-item request counts) — exactly the workload shape
  of the KohakuGBC evaluation (Bead `dhb`). If that lane ever runs inside this repo at scale,
  Togeari is the credible boring-established option for its execution.
- **Where it does not fit:** everything the catalog does today. Bounded single-request
  metadata sync is an audited transaction, not a throughput job; a dispatcher machine around
  one HTTP call per run is pure overhead. A plain asyncio/queue design already covers
  anything we currently run; Togeari's value appears only with (a) cross-job GPU batching,
  (b) exact-sequential semantics under real concurrency, (c) many jobs with divergent call
  graphs.
- **Boundary (unchanged, now informed):** Togeari owns execution only. Source identity,
  duplicate relationships, metadata, raw observations, and processing history stay in the
  kernel; if it is ever adopted, the seam is our existing run contract feeding a lane, never
  the kernel bookkeeping bending to a dataflow abstraction.

**Conclusion: no adoption now.** Record this note; revisit only when a concrete in-repo
branching multi-model pipeline exists (the `dhb` evaluation is the leading candidate to
reveal one).
