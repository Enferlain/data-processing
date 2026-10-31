# Proposal

## Why

The remaining-adapter lane (maintainer pick 2026-10-31, Bead `data-processing-2e5`) starts
with the two instance-table additions both reference tools (gallery-dl, Grabber) list:
`rule34.xxx` — the gelbooru-0.2 sibling explicitly deferred by change
`extend-gelbooru-family-instances` because its dapi demanded credentials — and `e926.net`,
the SFW instance of the e621 engine, which has no instance registry at all yet (the adapter
is welded to the single canonical `E621` constant). Live probes on 2026-10-31 confirmed
both contracts are reachable: `api.rule34.xxx` answers its dapi with
"Missing authentication" (credentials now supplied by the maintainer via the external
`RULE34_USER_ID` / `RULE34_API_KEY` environment), and `e926.net` answers anonymously with
the current e621-family post schema (verified by live capture of post 6823045).

## What Changes

- `e621` generalizes to a registered instance family (`E621_INSTANCES`: `e621`, `e926`),
  following the `GELBOORU_INSTANCES` / `SankakuInstance` pattern: `E926` declares its own
  platform key, base URL, host, and `e926-json-v1` schema version. Credential policy is
  unchanged (optional unless partial, same env names — `e926` accepts anonymous requests).
- `rule34` joins `GELBOORU_INSTANCES` as a credentials-required dapi instance
  (`rule34-json-v1`), with credential envs `RULE34_USER_ID` / `RULE34_API_KEY` and the dapi
  base `api.rule34.xxx` (the www host serves a CAPTCHA wall, not an API). The anonymous
  HTML transport stays gelbooru.com-only.
- Both new platform keys register in `SOURCE_OPERATIONS`; platform rows are
  migration-seeded (`0022`).
- CLI surfaces that construct the e621 adapter select the instance explicitly
  (`--instance e621|e926`); gelbooru-family commands gain `rule34` in their instance
  choices.
- Both instances land with **live-captured, redacted fixture suites** before their response
  contracts are treated as verified; no synthetic shapes. The e926 capture (post 6823045)
  exists; the rule34 capture happens under the maintainer's credentials.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `e621-metadata-adapter`: the adapter's requirements generalize from one canonical
  instance to a registered family of e621-engine instances with per-instance identity and
  schema versions, keeping the existing credential policy.
- `gelbooru-metadata-adapter`: no spec delta — its instance-family requirement is already
  membership-agnostic; `rule34` is implementation, registration, and a live-captured
  fixture under the existing requirements.
