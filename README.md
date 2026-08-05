# Data processing tools

Small, local-first tools for collecting and processing personal data.

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
