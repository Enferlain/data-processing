## Context

Metadata adapters persist normalized posts and media occurrences, while explicit acquisition accepts
`media_occurrence_id:variant_key` selections. The current public queries cover search, links,
metadata runs, acquisition runs, and stored assets, but no query joins the normalized occurrence
records into a safe browsing view. The schema already contains every required relationship, so this
is a query and interface change rather than a migration.

## Goals / Non-Goals

**Goals:**

- Provide a stable read-only bridge from synchronized metadata to explicit acquisition selections.
- Keep list queries bounded, keyset-paginated, deterministic, and safe on SQLite installations
  without optional JSON or FTS features.
- Reuse the acquisition planner's variant parsing and eligibility rules so browsing cannot advertise
  a selection that planning interprets differently.
- Preserve author, source-assertion, and verified-asset provenance while omitting sensitive URL and
  path fields.

**Non-Goals:**

- Schema changes, network access, account crawling, download execution, automatic variant choice,
  similarity scoring, work grouping, or identity/attribution conclusions.
- Returning raw provider payloads, rendered media URLs, managed paths, or legacy source paths.
- A general-purpose SQL or arbitrary sort/query interface.

## Decisions

### 1. Add a focused media query facade

Add `media_catalog.media_queries` with `list_media_occurrences`, `get_media_occurrence`, and a small
`MediaQueryService` facade. Follow the existing asset/acquisition query convention: accept either an
open `CatalogDatabase` or a catalog path, and use `CatalogDatabase.open_read_only` for path calls.
This keeps CLI code thin and makes the same response contract available to future workflow code.

An alternative was to add methods directly to `CatalogDatabase`. That would mix application-level
joins and output policy into the migration/search boundary and make the already central database
class broader.

### 2. Page by occurrence identifier before loading related collections

Select a bounded page of occurrence IDs ordered by `media_occurrence_id`, using a strictly-greater
continuation. Apply platform, author, post, availability, and linked-state filters in that ID query.
Then load authors, linked assets/fingerprints, and occurrence-source classifications in bounded
secondary queries for only those IDs. This avoids join multiplication and does not require SQLite
JSON aggregation.

The public limit is positive and capped. Fetch one extra ID to determine whether a continuation
exists; never return an unbounded result. Arbitrary offsets and caller-selected sort expressions are
excluded because they are less stable and expand the query-injection surface.

### 3. Share variant parsing and eligibility with acquisition planning

Extract the pure occurrence/variant interpretation needed by `plan_acquisition` behind a public,
side-effect-free helper or equivalent focused module. Both browsing and planning consume the same
validated representation. Detail output lists deterministic variant keys plus eligibility,
exclusion reason, policy identity, and satisfied asset ID, but never the selected URL or its host.

List output may use the same evaluator to provide a compact acquisition summary. Malformed,
ambiguous, or unsupported targets remain visible with bounded reasons instead of failing the full
page.

Duplicating a simplified eligibility implementation was rejected because the two interfaces would
eventually disagree on unusual Pixiv archives, preview variants, or provider-policy changes.

### 4. Use public stable account and post filters

The author filter accepts `platform:native_account_id`; post filtering accepts either the internal
positive post ID or an unambiguous `platform:native_post_id` reference. Internal occurrence IDs stay
public because they are the acquisition selection key. Account snapshot names and handles may be
shown as temporal display metadata, but they are not filter identity.

### 5. Build a deny-by-default output projection

Queries enumerate allowed output columns rather than converting `SELECT *` rows. Remote/canonical
URLs, `variants_json`, raw payloads, request data, root/path columns, and staging/quarantine names
never enter the public response. Occurrence sources are summarized by kind and safe identifiers;
linked assets expose calculated facts and relationship labels but no locations.

## Risks / Trade-offs

- [A post with many authors, assets, or sources can enlarge a detail response] → Return only bounded
  related collections in deterministic ID order with counts/truncation metadata where necessary.
- [New catalog rows inserted between pages can change a live traversal] → Keyset pagination prevents
  duplicates from earlier IDs; document that a listing is not a database snapshot.
- [Temporal handles could look authoritative] → Always pair display metadata with stable platform
  and native account identity and label participation role.
- [Eligibility evaluation adds work to listings] → Cap pages and reuse pure local evaluation; no
  network or filesystem access is permitted.

## Migration Plan

No database migration is required. Add the query API, CLI commands, tests, and documentation. The
change is additive and can be rolled back by removing those code paths without modifying catalog
data.
