# Proposal

## Why

The gelbooru dapi/HTML adapters already speak the gelbooru 0.2 engine protocol, but the
instance config is welded to gelbooru.com — `GelbooruInstance` raises unless
`platform_key == "gelbooru"` — so the rest of the engine family (safebooru.org, rule34.xxx,
and siblings) is unreachable even though reference tools (gallery-dl `gelbooru_v02`,
Grabber "Gelbooru (0.2)") prove the shared protocol. The repo just settled the
multi-instance pattern (DanbooruInstance: danbooru + aibooru) and the per-platform
operation registry (`SOURCE_OPERATIONS`), so the family is now cheap to admit honestly.

## What Changes

- `GelbooruInstance` generalizes to multi-instance following the `DanbooruInstance` pattern:
  per-instance `platform_key`/`base_url`/`host`/credential-env names/schema versions, with
  the platform-key lock replaced by family-key registration. Shipped instances:
  `GELBOORU` (unchanged) and `SAFEBOORU` (safebooru.org). `RULE34` (rule34.xxx) is
  deliberately deferred: its dapi requires credentials this environment does not carry, and
  the r4y lesson (synthetic fixtures lie — the gelbooru notes contract turned out to be XML,
  not JSON) forbids landing an instance against an unverified response shape.
- Per-instance dapi credential policy: gelbooru requires credentials (unchanged);
  safebooru declares anonymous dapi allowed, so credentials are optional for it and the
  adapter enforces the policy per instance. The anonymous HTML transport stays
  gelbooru.com-only in this change.
- Every new instance lands with a **live-captured, redacted fixture suite** (anonymous dapi
  for safebooru) before its response contract is treated as verified; no synthetic shapes.
- New platform keys register in `SOURCE_OPERATIONS` (the per-platform operation registry),
  and CLI surfaces gain explicit instance selection (`--provider` choices for lookup and
  reprocess; gelbooru metadata/enrichment commands select the instance explicitly).
- Bounded reverse lookup stays gelbooru-only in this change: safebooru ships with empty
  lookup capabilities (a conscious deferral; the dapi lookup endpoints exist, but each
  lookup strategy needs its own captured fixture before it is declared).

### Non-goals

- rule34.xxx (blocked on credentials for a live capture), further family members, HTML
  transports for new instances, and lookup strategies for new instances.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `gelbooru-metadata-adapter`: the adapter's requirements generalize from one canonical
  instance to a registered family of gelbooru-engine instances with per-instance identity,
  credential policy, schema versions, and fixture-verified response contracts.
