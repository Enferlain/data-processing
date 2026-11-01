# Design

## Context

Every adapter family already commits its contract as suite-format fixtures
(`manifest` + `cases` with `expected` facts) and normalizes through the shared
`fetch`/`normalize` envelope protocol — including pixiv, whose transport differs at the
HTTP layer but not at the envelope layer. That uniformity is what makes a generic
doctor cheap: one engine, one registration table, no per-family branching in the
comparator.

## Goals and Non-Goals

Goals: one command answering "do all adapters still honor their captured contracts, and
are the providers reachable"; named per-case failures; live checks that respect pacing,
credential policy, and the metadata-only stance.

Non-goals: exact per-family fact re-pinning (family tests own that), lookup-suite
replay, retiring the ad-hoc live smoke tests, scheduling.

## Decisions

### D1: The comparator checks the common contract core, exactly

Per case: (1) `manifest.adapter_version` and `manifest.schema_version` must equal the
live adapter's — a suite pinning an older version is itself a finding; (2) the expected
`outcome` must match — success cases normalize without raising, failure cases raise the
named typed outcome; (3) expected `post_ids`/`account_ids`, when present, must be a
subset of the normalized top-level ids; (4) every top-level normalized item's
`platform` datum must equal the suite's instance key. Anything else (scores, tag
counts, variant shapes) stays pinned by the family tests. This keeps the doctor honest
across eleven heterogeneous `expected` vocabularies without duplicating them.

### D2: Offline replay derives a synthetic request target per case

Fixture cases do not carry request targets (envelopes require one). The doctor derives
`doctor:<case-name>` — opaque to every adapter, and deliberately unparseable as a
listing target so listing continuations resolve terminally, which is exactly the
offline-replay semantics both gelbooru and pawchive already specify for targetless
envelopes.

### D3: Live probes reuse the suites' own targets and the adapters' own policy

Each registration names its probe case (a success `fetch_post`/`fetch_account` case),
so the probe target is always one the captured contract already covers — and a
registration naming a case its suite does not contain is reported as a failure, not a
skip. Probes run through the real adapter (`fetch` + `normalize`) with real clients and
pacing floors; credentials resolve from each family's existing environment convention
(the danbooru family probes anonymously when its environment is empty, like e621, while
gelbooru/rule34/sankaku/pixiv declare their credentials required) and missing
credentials are a SKIP with a named reason, never a silent success. The `--live` flag
itself is the operator authorization — a doctor run is an explicit operator action,
unlike a pytest invocation, so no additional acknowledgment variable is layered on top.
Transport and normalizer exceptions during replay or probing are contained into the
failing row's reason; the doctor names drift, it never crashes on it.

### D4: One registration table, no reflection

`DOCTOR_SUITES` maps fixture filename → adapter factory + instance + probe case name +
live credential policy. Adapters are constructed the way their family tests construct
them for offline normalization (dummy credentials where a constructor requires them;
pixiv with its explicit base URL and no refresh token). The table is data; adding a
future platform means adding one row and its fixture.

## Risks / Trade-offs

- The doctor's subset checks are weaker than the family suites — by design; it is the
  always-run tripwire, not the only net.
- Live probes hit real providers; they are bounded to one request per platform, honor
  each adapter's pacing floor, and touch metadata endpoints only.
- Fixture-derived probe ids can vanish upstream (deleted posts); the probe then reports
  the adapter's typed outcome (e.g. `deleted`) rather than pretending drift.

## Migration Plan

None: no schema, no persistence. The doctor is a read-only surface.

## Open Questions

- None blocking.
