# Design

## Context

Two precedents govern instance additions: `extend-gelbooru-family-instances` (safebooru)
and `add-sankaku-metadata-adapter` (instance table from day one). Both landed the instance
config, kernel registration, migration-seeded platform row, CLI instance selection, and a
live-captured fixture suite as one unit. The r4y rule is absolute: a response contract is
verified only by live capture, never by synthetic shapes.

## Goals and Non-Goals

Goals: admit `e926` and `rule34` as first-class instances of their existing engine
adapters; keep every existing instance's behavior unchanged; verify both new contracts by
live capture.

Non-goals: new adapters (both reuse existing engine code), lookup strategies for the new
instances, HTML transports, and further family members.

## Decisions

### D1: e621 gains the instance-registry pattern, not a new adapter

`E621Instance` already accepts per-instance fields; only the welded `E621` constant usage
in CLI construction sites blocks siblings. `E621_INSTANCES: dict[str, E621Instance]`
mirrors `GELBOORU_INSTANCES`; `E926 = E621Instance(platform_key="e926",
base_url="https://e926.net", host="e926.net", schema_version="e926-json-v1")`. Credential
envs stay the e621 pair (both instances accept anonymous; partial credentials remain an
error). The live capture (post 6823045) shows the current e621-family schema — newer keys
than the 2026-08 e621 fixture (`approver_id`, `change_seq`, `duration`, `has_notes`,
`uploader_name`, `vote`, `tags.contributor`/`invalid`, `flags` lock trio,
`relationships.children`) — which the existing normalizer handles defensively per key;
`e926-json-v1` names that captured generation. e926 ships with **empty lookup
capabilities**: each bounded lookup strategy must earn its own e926 captured fixture
before it is declared (the safebooru/rule34 precedent), so lookup provider choices stay
e621-only for now and the planner cannot route strategies to e926.

### D2: rule34 lives on `api.rule34.xxx`, credentials required

Live probes: `https://api.rule34.xxx/index.php?page=dapi&s=post&q=index&json=1` answers
`"Missing authentication. Go to api.rule34.xxx for more information"`; the www host
serves a CAPTCHA HTML page. So the instance's dapi base URL is `https://api.rule34.xxx`
(host `api.rule34.xxx`) with `dapi_credentials_required=True` and envs
`RULE34_USER_ID` / `RULE34_API_KEY` (values stay outside the repository, gelbooru.env
precedent). `rule34-json-v1` is declared only after the maintainer-keyed live capture
lands; if the capture reveals surprises (r4y's XML notes precedent), the fixture records
the bytes as served, not as documented.

### D3: one migration, two platform rows

`0022_add_e926_rule34_platforms.sql` inserts both rows (`e926` → `https://e926.net`,
`rule34` → `https://api.rule34.xxx`) with `INSERT OR IGNORE`, the safebooru/aibooru
precedent. `SOURCE_OPERATIONS` gains both keys with `REMOTE_OPERATIONS`, so kernel
admission and persistence agree.

### D4: CLI instance selection mirrors the gelbooru family

Every e621 adapter construction site resolves through `E621_INSTANCES[arguments.instance]`
with an explicit `--instance` choice (`e621` default). Gelbooru-family `--instance`
choices gain `rule34`.

## Risks / Trade-offs

- rule34.xxx is an adult-content instance; the adapter is metadata-only (no media bytes),
  and the fixture captures post metadata only — same stance as every other instance.
- If the maintainer key cannot exercise a dapi operation the adapter ships (e.g. notes),
  that operation stays uncovered by a fixture and the spec keeps it unverified rather than
  synthetically pinned.

## Migration Plan

Single forward migration `0022`; no data migration (new platform rows only). Existing
databases apply it on next open; no backfill needed for rows that never referenced the
new keys.

## Open Questions

- None blocking: both captures are either in hand (e926) or unblocked (rule34 key
  supplied by the maintainer).
