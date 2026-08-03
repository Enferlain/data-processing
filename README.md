# Data processing tools

Small, local-first tools for collecting and processing personal data.

## X likes archiver

`x-likes` imports the liked-post list found in an X account archive into SQLite. It can
then enrich each post through the public FxTwitter API and, when requested, download images
with exact and perceptual hashes.

The source can be the archive ZIP downloaded from X, its extracted directory, or the
`data/like.js` file itself.

```bash
# Install the locked environment and show CLI help.
uv sync
uv run x-likes --help

# Import and enrich metadata. No images are downloaded by default.
uv run x-likes /path/to/x-archive.zip

# Also download images.
uv run x-likes /path/to/x-archive.zip --download-images

# Import locally without contacting any third-party service.
uv run x-likes /path/to/x-archive.zip --import-only
```

Output defaults to `x-likes-output/`:

```text
x-likes-output/
├── likes.sqlite3
└── media/
    └── author_handle/
        └── 1234567890123456789_01.jpg
```

The database retains the archive text and complete raw provider JSON alongside normalized
post, account, and image fields. The `accounts` table stores the account ID, handle, display
name, bio, profile/avatar/banner URLs, website, location, follower counts, verification data,
fetch time, and raw account JSON. Account details are a snapshot from enrichment time rather
than necessarily the values shown when the post was originally liked.

If a database was created with an earlier version of this tool, run once with `--refresh` to
populate its normalized `accounts` table from fresh provider responses.

Downloaded images receive MD5, SHA-256, and perceptual hashes. Hashes require reading the image
bytes and are therefore only created with `--download-images`. MD5 is included only for matching
existing collections; SHA-256 is the exact-file identity.

### Operational notes

- The default metadata provider is the unaffiliated, third-party FxTwitter service. Running
  without `--import-only` sends each liked post ID to that service.
- Requests are sequential and delayed by 0.5 seconds by default. Increase this with `--delay`
  if the service asks you to slow down.
- Deleted, private, blocked, suspended, age-restricted, or otherwise unavailable posts may
  retain only the ID, URL, and text present in the original X archive. Provider tombstone
  reasons are recorded in the database.
- X documents the archive as machine-readable HTML/JSON, but does not publish a stable schema
  for the observed `data/like.js` file. The parser accepts known field variants and split like
  files, but the original archive should still be retained.
- Keep the downloaded X archive and generated output private. They can reveal sensitive
  account activity even when the liked posts themselves are public.
- Re-running the command is resumable. Already enriched posts and downloaded images are
  skipped unless `--refresh` is supplied for metadata.

## Development

```bash
uv run ruff check .
uv run pytest
```
