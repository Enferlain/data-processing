# KohakuGBC evaluation on the local stack (research note)

Status: measured 2026-10-30/31 (Bead `data-processing-dhb`); quantitative results complete,
maintainer quality review pending. No product surface changes.

## Setup

- `kohakugbc` + `kohakugbc-data` from the local clone (isolated `.venv-eval`; `togeari` also
  installed from its local clone — PyPI 0.3.0 lags KohakuGBC's `togeari.cli.commands.serve`).
- VLM over the maintainer's llama-swap (OpenAI protocol, `llama.cpp` flavour,
  `qwen3.5-4b-mem-mtp` = `vision-llm`), `max_inflight` throttled to 4: the first unthrottled
  run wedged the server (96 submissions, 72 retries, 16 failovers, all graphs empty via
  fault-swallowing, then the service died). Throttled: 2,580 calls, zero retries, server
  healthy after.
- Detectors on the RTX 3090 (`cuda:0` in torch numbering): OWLv2 default pass, then the
  SAM 3 layer (`facebook/sam3.1` local snapshot, `model_type: sam3`, bfloat16).
- Embedder: EmbeddingGemma-300m from a local snapshot (the HF-gated default; briefly ran an
  all-MiniLM stand-in before the maintainer supplied model files). Both gated models load
  from `eval-input/models/` — no HF token in play.
- 12 maintainer-selected ComfyUI outputs (`eval-input/`); configs
  `configs/machine/llamaswap_api.py` (+`llamaswap_sam3.py` layer) in the KohakuGBC clone;
- Non-fatal: triton driver-compile warnings on this NixOS toolchain (kernel backend
  fallback); a `transformers` `use_fast` deprecation notice.

## Results (12 images, both passes 12/12 jobs)

| Pass | Wall | Per image | Median vertices/captions/edges | Max v/c |
|---|---|---|---|---|
| OWLv2 | 307 s | 25.5 s | 16 / 24 / 36 | 29 / 53 |
| SAM 3.1 | 498 s | 41.5 s | 28 / 51 / 49 | 31 / 61 |

SAM 3 costs ~1.6x time and nearly doubles graph richness. On the image with the largest gap,
OWLv2 yielded 15 entities (subject + clothing parts) where SAM 3.1 yielded 29, adding the
scene layer (bed, table, table_lamp, bed_sheet, floral pattern) and object sub-structure
(bow loops, ribbon facets) — the README's illustration claim, reproduced on this stack.
Graph structure: caption→phrase→entity edges on vertices (`in_edges`/`out_edges`), sub/super
mask hierarchies, normalized boxes, layered short/detail captions.

Outputs: `~/Projects/sd-scripts-resources/KohakuGBC/runs/machine/{llamaswap_api,llamaswap_sam3}/
graphs.jsonl` (one JSON line per image; `img_path` names each) for the maintainer's
hallucination/region review.

## Notes for any catalog-side adoption later

- The VLM-over-API path works with the `llama.cpp` flavour but the server must be treated as
  fragile under burst: throttle inflight, expect fault-swallowed empty graphs on schema
  failures (the failures file, not the job counter, is the truth).
- Embedding models are HF-gated; local snapshots in `eval-input/models/` load fine via
  absolute `model` paths.
- Nothing here changes the repo: evaluation only. If GBC graphs ever become a catalog
  observation family, the enrichment-contract pattern (bounded run, raw report retained) is
  the natural surface, and Togeari's investigation (Bead `164`) already frames the execution
  boundary.

## Maintainer review (2026-10-31)

- `ComfyUI_05211_.png`, `ComfyUI_10630_.png`: mostly okay. `ComfyUI_08315_.png`: okay —
  **NSFW content mostly ignored** by the VLM (qwen3.5-4b under-describes it; a real
  coverage limitation for this corpus).
- `ComfyUI_03874_.png`: **full-scene confabulation confirmed.** The image shows a single
  character (maintainer ground truth), but the served VLM consistently describes a
  two-character interaction (a black-tailed male figure over a white-haired cat-eared girl)
  — stable across the run and two independent differently-phrased probes, so re-asking the
  same model cannot catch this class of failure; it needs cross-model or human verification.
  (The earlier suspected caption/image mismatch was disproven: the wrong description is
  consistently attached to the right file.)

Verdict: the pipeline and graphs are usable on this stack, with three reliability caveats:
the fragility of the llama-swap VLM under burst (throttle; the failures file is the truth),
the NSFW blind spot of the served model, and confirmed whole-scene confabulation on at least
one image — per-image sanity checks must not trust the same model to check itself. SAM 3.1's
structural advantage is real.
