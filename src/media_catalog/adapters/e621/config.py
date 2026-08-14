"""e621 metadata adapter configuration, category mapping, and schema audit.

This module is the single source of truth for the e621 provider policy: canonical
API host, descriptive non-browser User-Agent, page-size ceiling, one-second
minimum pacing, credential-reference names, and adapter/schema versions.  It also
records the schema-audit conclusions for OpenSpec change
``add-e621-metadata-adapter`` (task 1.1).

Schema audit (task 1.1) -- e621 facts mapped to neutral catalog records
----------------------------------------------------------------------

The adapter normalizes e621 responses into provider-neutral ``NormalizedItem``
values and the complete raw response is retained through the existing raw
observation mechanism.  Every required e621 fact maps as follows:

Post / media / attribution facts (representable losslessly today):

* post identity, created_at, updated_at, rating, availability
  -> ``PostRecord`` (``posts``).
* original ``file`` md5/ext/size/width/height and url
  -> ``MediaOccurrenceRecord`` declared_md5 / declared_file_size / width /
  height / mime_type / remote_url.
* sample and preview representations
  -> named entries in ``MediaOccurrenceRecord.variants_json``; each variant
  carries only its own url/dimensions and never inherits the original's declared
  md5/size (task 3.2).
* nested ``tags`` grouped by category
  -> ``TagObservationRecord`` (``tags`` / ``post_tags`` /
  ``post_tag_observations``).
* artist record (name, other_names, group_name, urls, deleted/banned flags)
  -> ``AttributionRecord`` (``attribution_entities`` / ``_names`` / ``_urls``).
* sources[], parent/children relationships, uploader role
  -> ``PostExternalReferenceRecord``, ``post_relations``, accounts +
  ``post_participants`` (role ``uploader``).

Representability gaps (preserved in normalized item data plus raw until the
smallest neutral migration is applied):

1. Native tag-category identity.  The neutral ``tags.category`` CHECK is
   ``general, artist, copyright, character, meta, unknown``.  e621 categories
   are provider-specific numeric codes (0 general, 1 artist, 2 contributor,
   3 copyright, 4 character, 5 species, 6 invalid, 7 meta, 8 lore).  Known
   categories map losslessly; contributor/species/invalid/lore and any future
   category map to neutral ``unknown`` -- never ``general`` -- and their native
   label/code are preserved on the normalized ``post_tag`` item and in the raw
   response.  Migration 0009 adds generic native-category columns to tags and
   tag observations so unknown categories never collapse to ``general``.
2. Standalone tag-record facts (provider tag id, ``post_count``, ``is_locked``)
   use those generic tag columns with observation provenance.
3. Tag-alias edges (antecedent/consequent/status/timestamps) require a
   versioned neutral observation table; migration 0009 adds it without a
   provider-only table or JSON payload.
4. Score/counts, pool ids, and non-deletion flags require typed post
   observations and pool/flag links; migration 0009 adds those generic tables.

Migration conclusion (task 1.3): the audit proves that aliases, native tag
identity, score/counts, pools, and flags cannot be retained queryably by the
existing schema.  The additive migration preserves existing ids, keeps raw
observations as provenance, and leaves remote operation CHECK constraints
unchanged: ``fetch_tag`` and ``fetch_tag_alias`` are adapter-only metadata
operations until a later synchronization task explicitly wires them.  The
e621 platform row is already seeded by migration 0002 (the fresh-schema count
is seven after migration 0005 adds AIBooru).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from media_catalog.adapters.contracts import (
    AdapterOperation,
    EnumerationCapabilities,
    EnumerationCapability,
    LookupCapabilities,
    LookupCapability,
    LookupPlanContext,
    LookupStrategy,
)

PROVIDER_KEY = "e621"
ADAPTER_VERSION = "e621-native-v1"
SCHEMA_VERSION = "e621-json-v1"
CONTINUATION_VERSION = "e621-keyset-v1"
ENUMERATION_VERSION = "library-expansion-v1"

E621_BASE_URL = "https://e621.net"
E621_HOST = "e621.net"
# Descriptive, non-browser User-Agent as required by e621's API policy.
E621_USER_AGENT = "data-processing-tools/0.1 (metadata-only e621 catalog)"

MAX_PAGE_SIZE = 320
MINIMUM_INTERVAL_SECONDS = 1.0

# e621 numeric tag-category codes are provider-specific.  They are NOT a neutral
# vocabulary: preserve the native label and never treat the integer as universal.
E621_TAG_CATEGORY_CODES: dict[int, str] = {
    0: "general",
    1: "artist",
    2: "contributor",
    3: "copyright",
    4: "character",
    5: "species",
    6: "invalid",
    7: "meta",
    8: "lore",
}

# Neutral categories that map losslessly from a provider label.  Every other
# label maps to ``unknown`` (never ``general``) so provider meaning is not
# silently collapsed.
NEUTRAL_TAG_CATEGORIES = frozenset({"general", "artist", "copyright", "character", "meta"})

# Fixed iteration order so normalized tag items are deterministic across
# reobservation.  Recognized e621 categories first, then any future labels sorted.
TAG_CATEGORY_ORDER = (
    "general",
    "artist",
    "copyright",
    "character",
    "species",
    "meta",
    "lore",
    "contributor",
    "invalid",
)


def e621_category_label(code: object) -> str | None:
    """Return the native e621 category label for a numeric code, if known."""

    if isinstance(code, bool) or not isinstance(code, int):
        return None
    return E621_TAG_CATEGORY_CODES.get(code)


def neutral_category(native_label: str) -> str:
    """Map a native tag-category label to the neutral vocabulary.

    Known categories map losslessly; every other label (species, lore,
    contributor, invalid, or a future category) maps to ``unknown`` and is never
    silently reassigned to ``general``.
    """

    label = native_label.strip()
    return label if label in NEUTRAL_TAG_CATEGORIES else "unknown"


# Candidate-lookup capabilities (task 5.2).  e621 supports exactly the six
# bounded, exact reverse-lookup strategies below.  Arbitrary fuzzy/unrestricted
# artist text (``ARTIST_TEXT``) is deliberately excluded: e621 has no bounded
# artist-text contract, so it is rejected before any request rather than routed
# through unrestricted text search.  Declaring a capability is a hard contract:
# the adapter renders only these strategies and the planner excludes the rest.
E621_LOOKUP_CAPABILITIES = LookupCapabilities(
    tuple(
        LookupCapability(
            strategy,
            "attribution" if strategy.value.startswith("artist_") else "post",
            "keyset",
        )
        for strategy in (
            LookupStrategy.SOURCE_POST_URL,
            LookupStrategy.EXTERNAL_POST_ID,
            LookupStrategy.DECLARED_MD5,
            LookupStrategy.VERIFIED_MD5,
            LookupStrategy.ARTIST_EXACT_NAME,
            LookupStrategy.ARTIST_ALIAS,
        )
    )
)


@dataclass(frozen=True, slots=True)
class E621Instance:
    """Immutable e621 provider configuration and request-policy floors."""

    platform_key: str = "e621"
    base_url: str = E621_BASE_URL
    host: str = E621_HOST
    schema_version: str = SCHEMA_VERSION
    username_env: str = "E621_USERNAME"
    api_key_env: str = "E621_API_KEY"
    user_agent: str = E621_USER_AGENT
    minimum_interval_seconds: float = MINIMUM_INTERVAL_SECONDS
    page_size: int = MAX_PAGE_SIZE

    def __post_init__(self) -> None:
        if not self.platform_key or self.platform_key != self.platform_key.lower():
            raise ValueError("e621 platform key must be lowercase text")
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.hostname.lower() != self.host.lower()
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("e621 instance requires an HTTPS base URL on its declared host")
        if not self.schema_version or not self.username_env or not self.api_key_env:
            raise ValueError("e621 instance requires schema and credential references")
        if not self.user_agent.strip() or self.user_agent.lstrip().lower().startswith("mozilla/"):
            raise ValueError("e621 instance requires a descriptive non-browser User-Agent")
        # Provider policy floors are invariants: a caller cannot construct a
        # configuration that weakens e621's hard pacing or page-size ceiling.
        if self.minimum_interval_seconds < MINIMUM_INTERVAL_SECONDS:
            raise ValueError(f"e621 minimum interval must be at least {MINIMUM_INTERVAL_SECONDS}s")
        if isinstance(self.page_size, bool) or not 1 <= self.page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"e621 page size must be between 1 and {MAX_PAGE_SIZE}")

    @property
    def instance_key(self) -> str:
        # e621 has a single canonical instance; the instance key is the platform.
        return self.platform_key

    @property
    def enumeration_capabilities(self) -> EnumerationCapabilities:
        # Enumeration (artist-library expansion) is wired in task 6.x; declared
        # here so the capability version is centralized with provider policy.
        return EnumerationCapabilities(
            (
                EnumerationCapability(
                    "attribution", AdapterOperation.LIST_ACCOUNT_POSTS, ENUMERATION_VERSION
                ),
            )
        )

    @property
    def lookup_capabilities(self) -> LookupCapabilities:
        # The closed, exact reverse-lookup contract declared in task 5.2.  This
        # is the single source of truth for both the adapter and the neutral
        # planning context, so a plan's capability set is provider configuration
        # rather than a hardcoded provider string.
        return E621_LOOKUP_CAPABILITIES

    @property
    def lookup_plan_context(self) -> LookupPlanContext:
        """Provider-neutral planning identity for the e621 instance.

        provider/instance/adapter/schema identity is supplied here so the
        read-only planner never references a hardcoded provider string; the
        capability set is the exact six-strategy contract above.
        """

        return LookupPlanContext(
            provider=PROVIDER_KEY,
            instance_key=self.instance_key,
            adapter_version=ADAPTER_VERSION,
            schema_version=self.schema_version,
            lookup_capabilities=self.lookup_capabilities,
        )


E621 = E621Instance()
