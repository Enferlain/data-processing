# Design

## Context

`GelbooruInstance` (src/media_catalog/adapters/gelbooru/config.py) is single-instance by
construction: `__post_init__` raises unless `platform_key == PROVIDER_KEY`, `GELBOORU` is the
only shipped instance, and roughly seven CLI sites bind it directly (metadata commands,
enrichment, lookup, reprocess). `DanbooruInstance` already demonstrates the multi-instance
shape (danbooru + aibooru: per-instance platform key, base URL, schema version, credential env
names), and the kernel's `SOURCE_OPERATIONS` registry (Bead `data-processing-6y1`) is the
admission guard for new platform keys. The dapi capture utility (Bead `data-processing-r4y`)
can capture any instance's responses with redaction; the r4y outcome (the notes contract was
XML, not the documented JSON) is the standing reason captures come before parsing assumptions.

## Goals / Non-Goals

**Goals:**
- One honest slice: generalize the family machinery and land `safebooru` (anonymous dapi,
  captureable now) end to end.
- Keep every existing gelbooru.com surface byte-identical in behavior.

**Non-Goals:**
- rule34.xxx (no credentials here; cannot live-capture, and synthetic shapes are banned),
  further family members, HTML transport beyond gelbooru.com, lookup strategies for new
  instances (their fixtures need per-strategy captures), and any media acquisition.

## Decisions

### D1: Generalize `GelbooruInstance` in place, following `DanbooruInstance`
Fields stay; the `platform_key == PROVIDER_KEY` lock becomes membership in a module-level
`GELBOORU_INSTANCES: dict[str, GelbooruInstance]` registry (`gelbooru`, `safebooru`).
`instance_key == platform_key`; planning contexts keep `provider="gelbooru"` with the
instance key, exactly as the danbooru family does. Alternative — a separate family module —
rejected: the adapters, transports, and capture utility are shared; only identity and policy
are per instance.

### D2: Credential policy is a per-instance declaration
New field `dapi_credentials_required: bool = True`. `GelbooruAdapter` (and the dapi capture
path) raise before any request only when the *instance* requires credentials and none are
supplied; `SAFEBOORU` declares `False`, so anonymous dapi proceeds and credentials are optional.
Alternative — a sentinel "anonymous credentials" object — rejected: policy belongs to the
instance, not to forged credentials.

### D3: Per-instance schema versions, family adapter version
`SAFEBOORU` carries `safebooru-json-v1` as its dapi schema version (constant next to the
existing ones); `ADAPTER_VERSION` stays family-wide, matching how the danbooru family versions
its instances. If the safebooru capture shows field drift (older gelbooru 0.2 generation), the
fixture decides what the normalizer may require — no assumption lands before the capture.

### D4: CLI instance selection is an explicit flag, not command proliferation
The `gelbooru-dapi-*` commands gain `--instance {gelbooru,safebooru}` defaulting to `gelbooru`;
the HTML command stays canonical-gelbooru with no flag. Reprocess `--provider` gained
`safebooru` alongside the registry (its replay adapter resolves through `GELBOORU_INSTANCES`);
lookup choices stay four until per-strategy captures exist (review correction 2026-10-28 —
the original draft understated the reprocess wiring). Alternative — per-instance command
names, the commentary precedent — rejected at five dapi commands per instance; the flag keeps
the command surface finite and the selection explicit. `GELBOORU_DAPI_CREDENTIAL_GUIDANCE`
becomes instance-aware.

### D5: `safebooru` registers in `SOURCE_OPERATIONS` before any surface ships
`records/common.py` registry gains `"safebooru": REMOTE_OPERATIONS`; the adapter-contracts
registry test pins the new key set. HTML-only and lookup-only surfaces stay gelbooru-bound.

### D6: The safebooru contract lands capture-first
Run the capture utility against safebooru.org's anonymous dapi for one post (and the empty
result shape), redact (no credentials exist to leak), and build the instance fixture suite from
those bytes before wiring the normalizer. If safebooru's responses break a strict parser
assumption, the fixture — not documentation — defines the fix.

## Risks / Trade-offs

- **Field drift on older engine versions**: safebooru.org may omit fields gelbooru.com returns.
  Mitigated by D6 (capture-first) and per-instance schema versions; the normalizer accepts only
  what the captured contract shows.
- **Anonymous rate limiting**: no published safebooru limit; the family floor (2 s interval,
  2 MiB body cap, 15 s timeout) is retained unchanged, and anonymous access stays bounded-run
  only.
- **Registry sprawl**: each future family member needs a registry line, a `SOURCE_OPERATIONS`
  entry, and a captured fixture — deliberate friction (the 6y1 honesty guard), not accidental.
