"""Fixture seeds for the matching research spike.

Contains only public inputs: the cross-platform example groups transcribed
from docs/plans/test_list.md (provider URLs already tracked there) and the
deterministic sampling configuration. No bookmark-derived identifiers belong
here — build_manifest.py derives those from the local catalog at run time so
private data never enters the tracked tree.

Group notes (from test_list.md): group 3 has three gelbooru variations —
"one is the same with and without text, and one different than the other 2" —
so group-3 inter-post pairs are measured as candidates rather than confirmed
same-work positives; the evidence document interprets them.
"""

from __future__ import annotations

# Cross-platform example groups: same underlying work observed on several
# providers. Only the X status ids and gelbooru post ids are fetchable here
# (X media via FxTwitter, gelbooru via retained DAPI captures); the pixiv,
# danbooru, e621, and baraag references are recorded for provenance only.
TEST_LIST_GROUPS: list[dict[str, object]] = [
    {
        "group": "g1",
        "x_status_id": "1950567258528547071",
        "gelbooru_post_ids": [12370900],
        "context_refs": [
            "pixiv:133416234",
            "danbooru:9714844",
        ],
    },
    {
        "group": "g2",
        "x_status_id": "1900654502380007860",
        "gelbooru_post_ids": [11605534],
        "context_refs": [
            "baraag:114162817218658720",
            "danbooru:8996458",
            "e621:5433323",
        ],
    },
    {
        "group": "g3",
        "x_status_id": "1837662117949800671",
        "gelbooru_post_ids": [10720246, 10791440, 10791439],
        "context_refs": ["danbooru:8186581"],
    },
]

# Deterministic sampling configuration for catalog-derived X fixtures.
X_SAMPLING = {
    # Number of distinct X media assets sampled for orig/small variant pairs.
    "variant_media_target": 60,
    # Random cross-author negative pairs among the sampled media.
    "cross_artist_pairs": 50,
    # Same-author, different-post pairs (visually related style/subject,
    # assumed different works; the evidence document flags any exceptions).
    "same_artist_pairs": 30,
    # Fixed seed so pair selection is reproducible across runs.
    "rng_seed": 20261004,
}

# Total fixture-file cap applied by build_manifest.py (truncation removes
# general X variant samples first and is recorded in the manifest header).
MAX_FIXTURE_FILES = 200

# Hosts the harness may contact. Image hosts are contacted by fetch.py;
# api.fxtwitter.com (JSON metadata only, the same service the x-likes tool
# uses) is contacted by build_manifest.py for the three test_list statuses.
ALLOWED_IMAGE_HOST_SUFFIXES = ("pbs.twimg.com", "gelbooru.com")
ALLOWED_METADATA_HOSTS = ("api.fxtwitter.com",)

GELBOORU_GROUP3_PAIR_CLASS = "gelbooru_group3_candidate"

# Pair classes treated as same-image/same-work positives in the threshold
# sweep. The group-3 candidate class is included with the caveat above: its
# pairs are measured same-work candidates, not confirmed labels.
POSITIVE_CLASSES = frozenset(
    {
        "x_variant",
        "gelbooru_sample",
        "gelbooru_preview",
        "cross_provider_same_work",
        GELBOORU_GROUP3_PAIR_CLASS,
    }
)
