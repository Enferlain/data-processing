# Gelbooru fixture contract

Reviewed provider contract behind `tests/fixtures/metadata_adapters/gelbooru.json` and
`gelbooru_html.json`. Everything here is either observed first-hand, corroborated by reference
implementations, synthetic, or explicitly unresolved. The adapter must not assume more than this
document records.

## Provenance

- **Observed** on 2026-10-01 (operator-authorized personal-use requests): five posts through both
  transports, one `s=tag` lookup, one nonexistent-post fetch, one anonymous fetch. Thirteen
  requests total, paced, metadata-only.
- **Corroborated** by local reference implementations: `gallery-dl`
  (`gallery_dl/extractor/gelbooru.py`) and imgbrd-Grabber (`src/sites/Gelbooru (0.2)/model.ts`).
- **Synthetic**: 403, 5xx, oversized, malformed, and error-envelope fixtures, plus marker-less
  HTML fail-closed pages. Manifests record this split.
- **Deferred**: rate limiting (`429`) and retry headers — never observed; no fixture exists.

## Request shapes

All requests target the canonical instance `https://gelbooru.com/index.php` with the descriptive
User-Agent from `GelbooruInstance`, no cookies, and no redirects followed.

| Transport | Parameters | Credentials |
| --- | --- | --- |
| DAPI post | `page=dapi&s=post&q=index&json=1&id=<positive numeric>` | required |
| DAPI tag | `page=dapi&s=tag&q=index&json=1&name=<tag>` | required |
| HTML post | `page=post&s=view&id=<positive numeric>` | forbidden |

Credentials (`user_id`, `api_key`) are query parameters joined only at the final HTTP boundary
(`GelbooruCredentials.authenticated_query`) and resolved all-or-nothing from
`GELBOORU_USER_ID`/`GELBOORU_API_KEY` before any network access. The catalog never requests media
bytes from image hosts.

## Response envelopes

- Current JSON shape: `{"@attributes": {"limit": int, "offset": int, "count": int}, "<key>": …}`
  where `<key>` is `post` (post queries) or `tag` (tag queries).
- `post` was observed as a **list** for `id=` queries; gallery-dl also handles a single **dict**
  and the legacy **bare array** format. Normalization must accept all three.
- Empty result: HTTP 200 with `@attributes.count == 0` and **no result key** (observed; gallery-dl
  relies on the same missing-key behavior).
- Error envelopes (corroborated by Grabber, not observed live): a bare JSON string body, a
  top-level `error` key (string or `{"#text": …}`), or `response.@attributes.success="false"` with
  a `reason`.
- Observed content types: `application/json; charset=UTF-8` (DAPI), `text/html; charset=UTF-8`
  (HTML, including the 401).

## Post record fields

All fields below were present on every captured post (five observations):

`change` (int), `created_at` (str, observed as ctime-like `Wed Jul 30 10:16:34 -0500 2025` with timezone offset; normalized to ISO UTC by adapter), `creator_id` (int, uploader),
`directory` (str), `file_url` (str), `has_children` (0/1), `has_comments` (0/1), `has_notes`
(0/1), `height` (int), `id` (int), `image` (str filename), `md5` (str), `owner` (str, uploader
name), `parent_id` (int or null), `post_locked` (0/1), `preview_height`/`preview_width` (int),
`preview_url` (str), `rating` (str: `general`/`sensitive`/`questionable`/`explicit` observed),
`sample` (0/1), `sample_height`/`sample_width` (int), `sample_url` (str), `score` (int),
`source` (str, URL or empty), `status` (str: `active` observed), `tags` (space-separated str),
`title` (str), `width` (int).

`declared hashes and URLs are provider assertions`; the catalog verifies nothing until its own
adoption path runs.

## Tag record fields

Observed `s=tag` result: `id` (int), `name` (str), `count` (int), `type` (int), `ambiguous`
(0/1). `type` is numeric; the only evidenced mapping is **1 = artist** (the same tag carries the
`tag-type-artist` class in captured HTML). The remaining mapping is unresolved (see below).

## Native tag-category evidence

- DAPI post records carry a flat `tags` string with **no** category information.
- DAPI tag records carry numeric `type` (evidence above).
- Captured HTML tag lists use `tag-type-<kind>` classes; observed kinds: `artist`, `copyright`,
  `general`, `metadata`.

## Pagination

- `pid` is a **0-based page number**, not a record offset (Grabber sends `page - 1`; gallery-dl
  increments it by one per page).
- `limit` is the page size, provider-capped at 100 (`MAX_PAGE_SIZE`; Grabber `maxLimit: 100`).
- `@attributes.count` reports the total result count.
- gallery-dl treats a page returning fewer than half the requested `limit` as terminal; the
  adapter's own boundary rules (task 3.4) govern our termination instead.

## Returned media variants

`file_url` (original), `sample_url` (present when `sample == 1`), `preview_url` (thumbnail).
gallery-dl notes video posts expose a `.webm` `file_url` whose playable path is derived from
`md5` plus the preview host. These URLs are retained as declared representations only.

## Status mapping

| Observation | Typed outcome |
| --- | --- |
| 200 with result records | `success` |
| 200 with `count == 0` / missing result key | `unavailable` |
| 401 (observed: empty body, also anonymous access) | `authentication_required` |
| 403 / challenge page | `authorization_denied` |
| 429 | `rate_limited` (deferred: no fixture) |
| 5xx | `transient_provider` |
| 200 with error envelope | typed failure / `malformed_response` |
| body over transport byte limit | `response_too_large` |
| unparseable JSON/HTML | `malformed_response` |

## Pacing and retry headers

Gelbooru documents no numeric rate limit and states throttling may occur; the adapter installs a
conservative 2.0-second floor (`MINIMUM_INTERVAL_SECONDS`), strictable but not weakenable. No
`Retry-After` or retry header was observed on any response; retry handling stays typed and
non-automatic until evidence exists.

## Redaction decisions (committed fixtures)

- Credential values never enter fixtures; request identities are semantic
  (`gelbooru:<transport>:post:<id>`).
- HTML bodies are reduced to title, `og:image`, the `id="image"` element, the tag list (capped at
  two entries per category; full spellings live in the DAPI bodies), and labeled statistics
  (`Posted:`/`Uploader:`/`Rating`/`Score`/`Size`/`Source:`).
- Inline scripts are removed and per-session anti-CSRF token values are scrubbed.
- Full untrimmed captures remain only in the gitignored `private-exports/gelbooru-captures/`
  staging area for deriving the HTML parser.

## Unresolved provider assumptions

1. The numeric tag `type` mapping beyond `1 = artist`.
2. Rate-limiting behavior and retry headers (never observed).
3. Whether real HTML not-found/challenge pages match the synthetic marker-less fixtures.
4. When the legacy bare-array and single-dict response forms occur on current endpoints.
5. Whether `status` values beyond `active` (deleted/pending/flagged) appear on DAPI records.
6. Gelbooru automation-policy posture over time; credentials do not grant permission, live use
   requires operator authorization (change task 8.2 will document this for operators).
