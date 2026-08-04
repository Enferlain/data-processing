# `x-likes` usage guide

`x-likes` builds a local SQLite archive of the liked-post records found in an exported X
account archive. It can enrich those records with current post and account metadata through
FxTwitter and can optionally download and hash post images.

The tool is resumable: running the same command again reuses the existing database, retries
ordinary fetch failures, and skips work already completed.

## What the tool collects

From the X archive, it imports the available post ID, URL, and archived text. During online
enrichment it can add:

- Current post text, URL, creation time, and availability status.
- Account ID, handle, display name, bio, profile URLs, website, location, follower counts,
  and verification details.
- Image URLs, dimensions, and alt text.
- The complete raw FxTwitter post and account responses for later reprocessing.
- For downloaded images: local path, file size, MD5, SHA-256, and perceptual hash.

Account and post metadata reflect the time of enrichment. They may differ from what was shown
when the post was originally liked.

## Requirements and setup

- Python 3.13 or newer.
- [`uv`](https://docs.astral.sh/uv/).

Run commands from the repository root:

```bash
uv sync
uv run x-likes --help
```

The equivalent module command is:

```bash
uv run python -m x_likes --help
```

## Obtain and select the input

Request and download your account archive by following
[X's archive instructions](https://help.x.com/en/managing-your-account/how-to-download-your-x-archive).
The tool does not request the archive on your behalf.

Keep the archive private. Depending on its contents, it may expose account activity, direct
messages, profile history, contacts, or other personal information beyond the likes processed
by this tool.

The positional `archive` argument accepts any of these forms:

1. The downloaded archive ZIP:

   ```bash
   uv run x-likes /path/to/x-archive.zip
   ```

2. The root of an extracted archive containing `data/like.js`:

   ```bash
   uv run x-likes /path/to/extracted-archive
   ```

3. The like data file directly:

   ```bash
   uv run x-likes /path/to/extracted-archive/data/like.js
   ```

The archive format is not a published, stable schema. The parser accepts known field variants
and split `like-part*.js` files, but you should retain the original archive in case a future
parser needs to recover additional information.

## Common workflows

### Import and enrich metadata

This is the normal mode. It imports every recognizable liked-post record into SQLite and asks
FxTwitter for current post, account, and image metadata. It does not download image files.

```bash
uv run x-likes /path/to/x-archive.zip
```

### Import, enrich, and download images

```bash
uv run x-likes /path/to/x-archive.zip --download-images
```

Each image is downloaded once. The tool calculates MD5 and SHA-256 from the exact downloaded
bytes and calculates a perceptual hash from the decoded image. Images are retained locally.

The tool currently downloads images only, not videos, animated video variants, or HLS media.

### Import without network access

```bash
uv run x-likes /path/to/x-archive.zip --import-only
```

This creates or updates the database using only the archive. It does not contact FxTwitter or
an image host. Because image URLs and bytes are not fetched, it cannot calculate image hashes.

`--import-only` cannot be combined with `--download-images`.

### Test a small enrichment batch

```bash
uv run x-likes /path/to/x-archive.zip --limit 25
```

`--limit` limits the number of posts enriched during that run. It does not limit how many
archive records are imported into SQLite, and it does not limit downloads for images already
known from earlier runs. Re-run without the limit to continue.

### Use a different output directory

```bash
uv run x-likes /path/to/x-archive.zip --output /path/to/private/x-likes
```

The repository ignores the default `x-likes-output/` directory. A custom output path is not
automatically ignored, so do not place private output in a tracked directory unless you add an
appropriate ignore rule.

### Refresh current metadata

```bash
uv run x-likes /path/to/x-archive.zip --refresh
```

Without `--refresh`, the tool fetches posts whose status is `pending` or `error`. It skips posts
already fetched successfully and posts recorded as unavailable. `--refresh` refetches all posts,
including those two skipped categories, and updates account snapshots.

Already downloaded images are not downloaded again merely because metadata is refreshed.
If refreshed metadata introduces a previously unknown image, a run that also uses
`--download-images` will download that new image.
In `--import-only` mode, `--refresh` has no effect because enrichment is skipped.

If the database was created by a version of the tool that predates the normalized `accounts`
table, run once with `--refresh` to populate it.

### Slow down provider requests

```bash
uv run x-likes /path/to/x-archive.zip --delay 2
```

The value is the number of seconds between metadata requests. The default is `0.5`; zero is
allowed. Increase it if the provider asks the client to slow down or if failures suggest a
temporary service limit.

## Command reference

```text
uv run x-likes ARCHIVE [OPTIONS]
```

| Argument or option | Meaning |
| --- | --- |
| `ARCHIVE` | X archive ZIP, extracted archive directory, or like data JavaScript file |
| `--output PATH` | Output directory; defaults to `x-likes-output` |
| `--download-images` | Download known images and calculate MD5, SHA-256, and perceptual hashes |
| `--import-only` | Import archive data without network requests |
| `--refresh` | Refetch metadata for every imported post |
| `--limit N` | Enrich at most `N` posts during this run; `N` must be greater than zero |
| `--delay SECONDS` | Delay between metadata requests; defaults to `0.5` and cannot be negative |
| `-h`, `--help` | Show the current command help |

## Progress and summary output

The command prints the import destination, per-post enrichment progress, optional image
download progress, and a final summary. A typical run includes lines shaped like:

```text
Imported 250 unique likes into x-likes-output/likes.sqlite3
[1/250] Enriched 1234567890123456789
Summary: 250 posts, 180 accounts, 230 enriched, 12 unavailable, 8 fetch errors, 90 images, 0 downloaded
```

Individual failures are printed to standard error and recorded in SQLite while processing
continues for the remaining records.

## Output layout

With the default output directory:

```text
x-likes-output/
├── likes.sqlite3
└── media/
    ├── account_handle/
    │   ├── 1234567890123456789_01.jpg
    │   └── 1234567890123456789_02.png
    └── unknown/
        └── 2345678901234567890_01.webp
```

Image filenames contain the post ID and one-based media index. The directory name is the
author handle when available. Downloads are limited to recognized images from `pbs.twimg.com`,
with a maximum size of 100 MiB per image. JPEG, PNG, WebP, GIF, and AVIF responses are accepted.

SQLite uses write-ahead logging, so temporary `likes.sqlite3-wal` and `likes.sqlite3-shm` files
may appear while the database is open. Keep them with the database if copying live output; for
a simple backup, stop the tool first and then copy the complete output directory.

## SQLite database

The database contains three primary tables.

### `posts`

One row per liked post. Important fields include:

- `post_id`, `post_url`, `archive_text`
- `author_id`, `author_handle`, `author_name`
- `post_text`, `created_at`, `imported_at`, `fetched_at`
- `fetch_provider`, `fetch_status`, `fetch_error`, `unavailable_reason`
- `raw_json`

`fetch_status` is one of `pending`, `fetched`, `error`, or `unavailable`.

### `accounts`

The latest account snapshot observed during enrichment, keyed by `author_id`. It contains the
handle without a leading `@`, display name, bio, profile/avatar/banner URLs, location, website,
counts, verification details, fetch time, and raw account JSON.

### `media`

One row per known image, keyed by post ID and media index. It stores the source URL, local path,
dimensions, alt text, file size, MD5, SHA-256, perceptual hash, and any download error.

### Example queries

The `sqlite3` command is optional but convenient:

```bash
sqlite3 x-likes-output/likes.sqlite3
```

`x-likes` does not currently provide its own query or export command. These examples use the
external `sqlite3` program; another SQLite client works as well.

Show liked posts with their current account identity:

```sql
SELECT
    p.post_id,
    '@' || a.handle AS account,
    a.display_name,
    p.post_text
FROM posts AS p
LEFT JOIN accounts AS a ON a.author_id = p.author_id
ORDER BY CAST(p.post_id AS INTEGER) DESC
LIMIT 20;
```

Show unavailable posts and fetch errors:

```sql
SELECT post_id, fetch_status, unavailable_reason, fetch_error
FROM posts
WHERE fetch_status IN ('unavailable', 'error');
```

Show downloaded image hashes:

```sql
SELECT post_id, local_path, md5, sha256, phash
FROM media
WHERE local_path IS NOT NULL;
```

## Resuming and recovery

Progress is committed incrementally. If a run is interrupted, repeat the same command with the
same archive and output directory:

```bash
uv run x-likes /path/to/x-archive.zip --download-images
```

- Previously imported posts are updated rather than duplicated.
- Successfully enriched posts are skipped unless `--refresh` is used.
- Ordinary fetch errors are retried on the next run.
- Unavailable posts are retained as tombstones and skipped unless `--refresh` is used.
- Images with a recorded local path are skipped.

Individual provider or image failures are recorded and printed, but do not abort processing of
the remaining records. Treat the final summary and the database error columns as authoritative.

Back up the entire output directory if you want both the database and downloaded files. Keep
the original X archive separately; the generated SQLite database is not a replacement for it.

## Privacy and service boundaries

- Default enrichment sends each liked post ID to the unaffiliated FxTwitter service.
- Image download requests go to X's `pbs.twimg.com` image host.
- `--import-only` avoids both kinds of network request.
- Raw provider JSON is retained and can contain more account or post metadata than the
  normalized columns.
- Deleted, private, blocked, suspended, age-restricted, or otherwise unavailable posts may
  retain only information present in the original archive.
- Keep the archive, SQLite database, media directory, and backups private.

FxTwitter is an external dependency and may change or become unavailable. The archive import
still works offline even when enrichment does not.

## Troubleshooting

### `Could not find data/like.js`

Pass the original archive ZIP, the extracted archive root, or the like file itself. If X has
changed the archive layout, locate the like data file and pass it directly.

### The like file contains records but no post IDs are recognized

The archive schema may have changed. Keep the original archive and update the parser before
discarding or rewriting any source data.

### Some posts show `error`

Network and temporary provider failures are recorded in SQLite. Re-run the command to retry
them. Consider increasing `--delay` if failures appear rate-related.

### Some posts show `unavailable`

The provider may report a post as deleted, private, blocked, suspended, or otherwise
unavailable. The tool preserves the archive record and provider tombstone. Use `--refresh` only
if you want to check those posts again.

### No images were downloaded

Confirm that:

- `--download-images` was supplied.
- The post was enriched successfully.
- The post contains supported images rather than only video or external media.
- The provider returned a valid `pbs.twimg.com` image URL.

Download failures are stored in `media.download_error` and retried while `local_path` remains
empty.

### The `accounts` table is empty

`--import-only` does not obtain account profiles. Run online enrichment, or use `--refresh` if
the database was populated by an earlier version of the tool.
