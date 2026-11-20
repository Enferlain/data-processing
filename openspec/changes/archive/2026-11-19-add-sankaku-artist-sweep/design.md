# Design

## Decisions

- **Ride the shipped listing, add only the driver.** `sankaku-list`
  (`LIST_ACCOUNT_POSTS`, keyset, fixture-backed) already does one target;
  the sweep is the same shape as `discover_pools` (ranked names, skip on
  prior complete runs, request budget, platform-floor pacing) — proven
  structure, second consumer.
- **Cross-platform name ranking.** Artist tag vocabularies are shared across
  booru conventions (`84v` research), so the name source is artist tags on
  danbooru, e621, and sankaku itself, deduplicated, ranked by total held
  posts, floor of three (one-off artists rarely justify a request).
- **The compare half is a read-only report, not a matcher.** The md5 join
  (sankaku declared md5 vs any other platform's md5) answers "known
  elsewhere vs new to catalog" today; similarity and media verification wait
  on the undecided channel (`ry2`) and later phases.
- **Failure containment per name.** A failing listing records the error in
  the sweep result and consumes its page budget estimate; the sweep
  continues. Budget accounting uses the sync result's `request_count` when
  present.
- **`--no-interval` is hidden, tests only.** Production invocations always
  pace at the adapter floor.

## Risks

- Sankaku API instability (host churn, quotas — `84v`): contained by the
  standard run contract; per-name failures never abort the sweep.

## Migration Plan

None — no schema change; the sweep writes ordinary sync runs and post facts.
