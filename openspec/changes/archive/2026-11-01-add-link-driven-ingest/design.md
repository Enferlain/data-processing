# Design

## Context

Three proven capabilities already exist: per-platform metadata sync (by internal
target), bounded lookup (by source URL, for four platforms), and managed asset
acquisition (for cataloged occurrences). The gap is the inch between a pasted URL
and the first one. Nothing new touches a provider wire, so no new captures are
required (the r4y rule governs response contracts; URL grammars are pinned by the
canonical URLs the captured normalizers already emit, and the resolver's test table
uses exactly those captured post ids).

## Goals and Non-Goals

Goals: every supported platform's post URL resolves offline to the target that
fetches it; one command runs the whole path; failures are actionable and named.

Non-goals: media bytes (assets pipeline owns them), account/pool grammars, lookup
strategies, and HTML scraping.

## Decisions

### D1: The resolver is a pure function over host+path+query

`resolve_link(url)` parses, matches the host against per-family resolvers, and
validates id grammar per family (digits for danbooru/e621/gelbooru/pixiv/pawchive,
opaque `[A-Za-z0-9]{4,32}` for sankaku). Every resolver returns the canonical URL
its platform's normalizer would emit, so round-tripping is self-checking. The
gelbooru family is query-shaped (`page=post&s=view&id=`) because that is both what
the adapter emits and what users paste; host determines the family instance
(`rule34.xxx`, `www.rule34.xxx`, and `api.rule34.xxx` all mean `rule34`).

### D2: `fetch` composes resolution with the existing sync path

A small factory (`_fetch_adapter_for`) maps each platform to the same adapter
construction the metadata commands use — instance registries, credential
resolution rules, pacing floors — so link-driven fetch follows command-driven
fetch. One deliberate narrowing: gelbooru-family links use the **DAPI transport**,
so `gelbooru.com` and `rule34.xxx` links require that family's credentials (the
error names the environment variables). The anonymous HTML transport stays an
explicit choice on its own command — silent transport fallback would contradict
the gelbooru adapter's explicit-transport requirement. `--resolve-only` stops
before opening the catalog. Pixiv's context-manager lifecycle is honored the same
way its own command honors it.

### D3: Zoneless pawchive timestamps qualify as UTC

End-to-end fetch exposed that kemono serializes naive stamps while the temporal
layer (`normalize_timestamp`) requires offsets — offline tests never persisted, so
the fixture suites could not catch it. The fix follows the repo's shipped
interpretation for zoneless provider stamps: the gelbooru HTML adapter appends UTC
to its `Posted:` values. Pawchive's `_timestamp` normalizes the same way and drops
unparseable values to absence rather than inventing them.

## Risks / Trade-offs

- URL grammars can drift if a provider restructures its site; the resolver's test
  table pins the current forms against captured post ids, and new grammars are
  additive rows.
- Qualifying zoneless stamps as UTC is an interpretation; it is pinned by test,
  documented in two adapters, and revisitable in one place per adapter if evidence
  ever contradicts it.

## Migration Plan

None: no schema, no persistence change. The pawchive adapter fix is behavior-only.

## Open Questions

- None blocking. Account/pool URL grammars are natural additive rows if wanted.
