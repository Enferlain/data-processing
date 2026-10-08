# Data processing

A local-first system for gathering, retaining, cross-referencing, verifying, and organizing data
from heterogeneous sources while preserving provenance and uncertainty.

Media is the first data family this repository works on, not the definition of the system. The
durable database is an evidence layer — raw observations, declared provider facts, locally
verified facts, and review history — and every consumer view over it is a projection with a
stated policy.

See the [project roadmap](ROADMAP.md) for current capabilities, active direction, and planned
work, and the [provenance kernel plan](docs/plans/provenance-kernel.md) for the domain-neutral
vocabulary the schema implements.

## How the repository is layered

Three layers make the architectural boundary legible. They are a documentation and spec model,
not separate packages — the names that intentionally stay media-shaped are listed in
[Names that are intentionally legacy or domain-local](#names-that-are-intentionally-legacy-or-domain-local).

1. **Provenance kernel** — the domain-neutral contracts every data family builds on: sources and
   source objects, append-only raw observations, provenance events, content-addressed blobs,
   declared-versus-verified facts, typed relationships with epistemic status, evidence and review
   ledgers, bounded runs, storage-enforced audit immutability, and projections with stated
   policies. Specified in the [kernel plan](docs/plans/provenance-kernel.md) and the
   [`provenance-kernel` capability spec](openspec/specs/provenance-kernel/spec.md).
2. **Media/social domain family** — the first and currently only data family: typed tables for
   accounts, posts, tags, media occurrences and variants, and bounded provider adapters for Pixiv,
   the Danbooru family, e621, Gelbooru, and X archive imports. Media-specific vocabulary such as
   dimensions, codec, and format lives in this layer, never in the kernel.
3. **Current workflows** — the applications runnable today: the standalone `x-likes` archive
   importer and the `catalog` CLI, which starts from imported likes and bookmarks and carries
   reviewed targets through link discovery, bounded lookup, metadata sync, occurrence browsing,
   and verified acquisition.

The kernel names what the schema already does. Concepts are promoted into it only when a second
consumer or a concrete workflow needs them — typed schemas over a small kernel, never a generic
entity-attribute-value soup.

## Names that are intentionally legacy or domain-local

None of these are renamed for cosmetic consistency. A name generalizes only when a second data
family or a concrete workflow requires it.

| Name | What it actually is | Why it keeps this name |
| --- | --- | --- |
| `media_catalog` (package) | The whole current implementation: kernel, media family, and workflows | Media is the only family so far; the boundary moves when a second one lands |
| `catalog` (CLI) | The main workflow surface over the kernel and media family | Mature CLI; renaming would break users without moving any boundary |
| `x-likes` (CLI) | Standalone X-archive importer that predates the catalog | Independent tool with its own storage |
| `platforms` (table) | Remote-provider registry; the kernel term is *source* | Per-family typed tables are the kernel pattern, not a shared registry |
| `observations` (table) | Provenance events: why a record is held (`liked`, `bookmarked`, `imported`, …) | Historical name; in kernel terms the unqualified word *observation* means a source report |
| `raw_observations` (table) | Source reports: what a source said and when, append-only | The kernel observation; never revised in place |
| `assets` (table) | Verified, content-addressed bytes — the kernel *blob* | Media-era name on a kernel concept |
| `media_occurrences` (table) | One observed representation of a work at a source — the kernel *representation* | Domain naming; the pattern is named in the kernel spec |

## What this can become

Because the evidence layer retains every observation and where each fact came from, later
surfaces are projections with stated policies rather than destructive migrations: media-library
views, training datasets with per-field source attribution, research tables, and bounded
JSONL/CSV exports. None of these projection surfaces exist yet — this is direction, not a
feature list — and any future projection must state its selection, ordering, and field-source
policy instead of silently choosing for you.

## Tool guides

- [`x-likes`](docs/tools/x-likes.md) — import and enrich liked posts from an exported X
  account archive, with optional image downloads and hashes.
- [`catalog`](docs/tools/media-catalog.md) — import existing likes and xarchive bookmarks into a
  platform-neutral, provenance-preserving SQLite catalog.

See the [tool guide index](docs/README.md) for the user-facing documentation convention used by
this repository.

## Quick start

```bash
uv sync
uv run x-likes --help
uv run catalog --help
```

## Development

```bash
uv run ruff check .
uv run pytest
```
