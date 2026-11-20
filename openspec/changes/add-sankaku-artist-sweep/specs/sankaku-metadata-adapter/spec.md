# sankaku-metadata-adapter Delta

## ADDED requirements

### Requirement: bounded artist sweep lists and compares

The catalog SHALL support a bulk sankaku sweep over the catalog's top artist
names: names ranked by held posts across the source platforms (floor of
three), one bounded keyset listing per not-yet-swept name under the standard
sync contract, prior complete listing runs skipped, per-name failures
contained (recorded, sweep continues), and a shared request budget with
platform-floor pacing between names. Every sweep SHALL conclude with the
md5 overlap report: sankaku posts whose declared md5 is known on another
platform versus md5s new to the catalog.

#### Scenario: sweep lists top artists and reports overlap

- **WHEN** `catalog metadata sankaku-sweep <catalog>` runs with name and
  request budgets
- **THEN** each not-yet-swept artist name gets one bounded listing run,
  already-complete names are skipped, and the result reports per-name
  outcomes plus the md5-known-elsewhere versus md5-new counts

#### Scenario: a failing artist does not stop the sweep

- **WHEN** one artist's listing fails
- **THEN** the failure is recorded for that name with its error and the
  sweep continues to the next name under the budget
