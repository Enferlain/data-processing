## Context

The catalog already seeds the `gelbooru` platform and recognizes query-style Gelbooru post and
artist URLs, while its provider-neutral sync, raw-retention, tag, post-fact, media-occurrence, and
query contracts are in place. It has no Gelbooru transport, fixtures, CLI path, or media policy.

Current official documentation describes a read-only DAPI with JSON selected by `json=1`, API-key
and user-ID query authentication, post/tag endpoints, default 100-record pages, and numeric `pid`
pagination. Anonymous DAPI currently returns HTTP 401. Public post HTML currently remains available,
and Grabber works without configured credentials by falling from failed API sources to its HTML
parser. The API does not document response fields, numeric tag-category codes, media hosts, alias or
artist endpoints, or a numeric rate limit. Gelbooru's terms also prohibit automated retrieval or
indexing broadly, so live operation must remain explicit, personal-use/authorization dependent,
bounded, and documented rather than scheduled or recursive.

## Goals / Non-Goals

**Goals:**

- Provide two independently versioned, explicitly selected metadata transports that converge on
  the same stable Gelbooru post identity.
- Capture and review redacted real-response fixtures before normalizing undocumented fields.
- Preserve raw DAPI JSON or HTML, transport identity, typed failures, provider assertions, and
  credential privacy through existing catalog contracts.
- Exercise the five Gelbooru posts in `docs/plans/test_list.md` without opening or downloading their
  images during metadata synchronization.

**Non-Goals:**

- Silent DAPI-to-HTML fallback, browser automation, cookies, session login, Cloudflare bypass, or
  scheduled/background crawling.
- Candidate lookup, library expansion, counts, aliases, pools, favorites, notes, deleted streams,
  media acquisition, or a generic Gelbooru-compatible engine abstraction.
- Cross-database tag aliasing, automatic artist/account/authorship decisions, visual similarity, or
  automatic same-work/variation labels.

## Decisions

### 1. Use a dedicated Gelbooru adapter with explicit transport mode

A dedicated provider package owns Gelbooru instance policy, credentials, DAPI request rendering,
HTML request rendering, response parsing, and normalization. The CLI requires a transport for
single-post fetch; DAPI-only list or tag commands state that boundary directly. Runs record the
transport key and version in their stable material and reject transport changes on resume.

This is preferable to subclassing the Danbooru adapter because the wire shape, authentication,
pagination, tag model, and error documents differ. It is preferable to Grabber-style fallback
because a fallback hides a policy change and can turn an API failure into a different retrieval
operation without user review.

### 2. Make fixture capture a gate, not an implementation afterthought

Before a parser field becomes normalized, capture minimal redacted DAPI and HTML responses for
posts `12370900`, `11605534`, `10720246`, `10791439`, and `10791440`, plus unavailable,
authentication/challenge, malformed, and exact-tag cases. Capture tools make no media requests,
strip credential-bearing request URLs from artifacts, record capture time and transport versions,
and replace sensitive free text or URLs only under a documented manifest.

Production raw observations remain the unmodified response bytes under existing private-data
policy; committed fixtures are deliberately redacted test artifacts. gallery-dl and Grabber remain
comparison oracles only and are not invoked at runtime.

### 3. Treat DAPI credentials as ephemeral query material

`GELBOORU_USER_ID` and `GELBOORU_API_KEY` are resolved together from the environment. A partial pair
fails before the request. The adapter creates the credential-bearing query only at the final HTTP
boundary; stable identities contain provider, transport, operation, target, page, limit, and
version but never the rendered URL or credential values. HTTP exceptions and diagnostics are
translated before they can expose a request URL.

The initial provider ceiling is 100 records per DAPI page. User budgets can narrow but never widen
the installed policy. No undocumented rate is claimed; use a conservative configurable minimum
interval and honor explicit provider retry information without busy waiting.

### 4. Limit HTML to one canonical post page and one response

HTML mode accepts a positive numeric ID and requests only
`https://gelbooru.com/index.php?page=post&s=view&id=<id>`. It uses a bounded non-browser HTTP client,
does not execute scripts, and parses the one response with a small standard-library-backed parser
whose accepted markers are fixture-characterized. It does not request HTML listings, tag pages,
notes, thumbnails, sources, or media links.

If the page becomes incompatible or presents a challenge, raw bytes are retained and normalization
fails closed. A future parser version may reprocess those observations without overwriting history.

### 5. Normalize shared facts conservatively

Both transports emit the existing normalized item vocabulary. Stable numeric post ID anchors
identity. Uploader remains a participant in uploader role, never artist. MD5, size, dimensions,
rating, score, source, and URLs remain provider assertions. Returned original/sample/preview URLs
become metadata-only named variants; absent URLs remain absent and are never reconstructed.

HTML category classes may map to artist, character, copyright, or general only after fixtures prove
them. DAPI tag strings lacking category evidence use neutral `unknown` plus native spelling. Numeric
tag type mappings, `limit=0` count semantics, and inferred video URLs from local reference tools are
not adopted without direct evidence.

### 6. Reuse response-first synchronization and neutral persistence

The shared executor retains each admitted response before normalization, commits normalized records
and continuations atomically, and exposes bounded typed outcomes. Add transport identity to the
provider request/continuation material without changing other providers' public behavior.

The existing platform, tag/native-category observations, post facts, media occurrences, raw
observations, and queries are expected to be sufficient. A migration may update Gelbooru platform
metadata or add a neutral field only after the fixture audit proves a gap; provider-specific JSON
columns or parallel Gelbooru tables are rejected.

### 7. Keep later workflows independently gated

Metadata support does not automatically declare lookup, expansion, or acquisition capability.
Source/MD5 lookup can follow after search response semantics are stable. Library expansion waits for
a stable provider attribution target and count/listing contract. Acquisition waits for fixture-
proven returned variant meanings, CDN/redirect host policy, and exact-claim boundaries.

## Risks / Trade-offs

- **Gelbooru terms may disallow the intended live behavior** → keep tests fixture-first, live tests
  disabled, document the operator authorization prerequisite, and never schedule or recurse.
- **HTML markup is unstable** → accept one page shape per parser version, retain raw bytes, fail
  closed, and never use it as an invisible fallback.
- **DAPI credentials appear in query parameters** → construct them only at transport time and scrub
  rendered URLs from every durable or public error path.
- **`pid` pages shift when posts change** → bind continuations to target, sort, transport, and
  version; describe resume as bounded observation rather than gap-free historical enumeration.
- **DAPI and HTML disagree** → retain both claims and apply documented current-projection policy;
  do not manufacture consensus.
- **Tag categories are incomplete** → preserve native spelling/code and neutral unknown rather than
  perform implicit per-tag fan-out or guess mappings.

## Migration Plan

1. Land fixture manifests and compatibility tests before enabling normalized field mappings.
2. Add configuration and adapter transports behind explicit CLI selection.
3. Add only fixture-proven neutral persistence changes and verify fresh/upgrade/rollback integrity.
4. Enable offline fixture tests by default; keep live metadata smoke tests opt-in and bounded.
5. Roll back by disabling Gelbooru CLI routing while retaining migrations and raw observations;
   never delete already retained provider evidence.

## Open Questions

- What conservative request interval should be the installed default when Gelbooru exposes no
  public numeric rate limit? This can be tightened without changing the external contract.
- Which response headers, if any, safely expose retry information in credentialed fixtures?
