from __future__ import annotations

import pytest

from media_catalog.links import (
    account_occurrences,
    canonicalize_url,
    post_occurrences,
    recognize_url,
)
from media_catalog.records import (
    PlatformReferenceRecord,
    validate_instance,
    validate_relation,
    validate_review_state,
    validate_source_context,
    validate_version,
)


@pytest.mark.parametrize(
    ("url", "platform", "instance", "kind", "native_id", "target"),
    (
        (
            "https://twitter.com/A/status/42?utm_source=x#z",
            "x",
            "",
            "post",
            "42",
            "https://x.com/i/status/42",
        ),
        (
            "https://www.pixiv.net/en/users/27631291",
            "pixiv",
            "",
            "account",
            "27631291",
            "https://www.pixiv.net/users/27631291",
        ),
        (
            "https://pixiv.net/artworks/133416234",
            "pixiv",
            "",
            "post",
            "133416234",
            "https://www.pixiv.net/artworks/133416234",
        ),
        (
            "https://danbooru.donmai.us/post/show/8186581",
            "danbooru",
            "danbooru.donmai.us",
            "post",
            "8186581",
            "https://danbooru.donmai.us/posts/8186581",
        ),
        (
            "https://e621.net/post/show/5433323",
            "e621",
            "e621.net",
            "post",
            "5433323",
            "https://e621.net/posts/5433323",
        ),
        (
            "https://baraag.net/@artist/114162817218658720",
            "mastodon",
            "baraag.net",
            "post",
            "114162817218658720",
            "https://baraag.net/@artist/114162817218658720",
        ),
        (
            "https://gelbooru.com/index.php?s=view&id=10720246&page=post",
            "gelbooru",
            "gelbooru.com",
            "post",
            "10720246",
            "https://gelbooru.com/index.php?page=post&s=view&id=10720246",
        ),
    ),
)
def test_recognizers_return_stable_typed_references(
    url: str, platform: str, instance: str, kind: str, native_id: str, target: str
) -> None:
    result = recognize_url(url)
    assert result.canonical.state == "recognized"
    assert result.reference == PlatformReferenceRecord(
        platform,
        instance,
        kind,
        native_id,
        target,
        result.reference.recognizer,  # type: ignore[union-attr]
        "platform-recognizers-v1",
    )


def test_canonicalization_is_conservative_and_retains_original_parts() -> None:
    result = canonicalize_url("http://Twitter.com/A/status/42?x=1&utm_source=z#section")
    assert result.canonical_url == "https://x.com/A/status/42?x=1"
    assert result.original_query == "x=1&utm_source=z"
    assert result.original_fragment == "section"
    unknown = canonicalize_url("http://example.test/path?utm_source=meaningful#frag")
    assert unknown.canonical_url == "http://example.test/path?utm_source=meaningful#frag"
    assert recognize_url(unknown.original_url).reference is None
    assert recognize_url("https://t.co/abc").canonical.state == "redirect_required"
    assert recognize_url("https://linktr.ee/name").canonical.reason == "link_hub"


def test_ambiguous_or_invalid_urls_do_not_fabricate_references() -> None:
    assert recognize_url("not a URL").canonical.state == "invalid"
    assert recognize_url("https://gelbooru.com/index.php?page=post&s=view").reference is None
    assert recognize_url("https://www.pixiv.net/users/not-numeric").reference is None


def test_mutable_account_handles_and_content_hashes_are_typed_explicitly() -> None:
    x_account = recognize_url("https://x.com/ArtistName").reference
    mastodon_account = recognize_url("https://baraag.net/@ArtistName").reference
    media = recognize_url(f"https://e621.net/data/{'a' * 32}.jpg").reference
    assert x_account is not None and x_account.identifier_kind == "handle"
    assert x_account.native_id == "artistname"
    assert mastodon_account is not None and mastodon_account.identifier_kind == "handle"
    assert media is not None and media.identifier_kind == "hash"


def test_instance_namespaces_are_part_of_reference_identity() -> None:
    configured_mastodon = frozenset({"one.example", "two.example"})
    first = recognize_url(
        "https://one.example/@artist/123", mastodon_instances=configured_mastodon
    ).reference
    second = recognize_url(
        "https://two.example/@artist/123", mastodon_instances=configured_mastodon
    ).reference
    assert first is not None and second is not None
    assert first.native_id == second.native_id == "123"
    assert first.instance_host != second.instance_host

    configured = {"one.example": "danbooru", "two.example": "danbooru"}
    one = recognize_url("https://one.example/posts/123", booru_instances=configured).reference
    two = recognize_url("https://two.example/post/show/123", booru_instances=configured).reference
    assert one is not None and two is not None
    assert one.native_id == two.native_id == "123"
    assert one.instance_host != two.instance_host


def test_arbitrary_at_path_is_not_assumed_to_be_mastodon() -> None:
    assert recognize_url("https://personal.example/@artist/123").reference is None


@pytest.mark.parametrize(
    ("url", "kind"),
    (
        ("https://danbooru.donmai.us/artists/55", "artist"),
        ("https://gelbooru.com/index.php?page=artist&s=show&id=55", "artist"),
        (f"https://e621.net/data/{'a' * 32}.jpg", "media_asset"),
    ),
)
def test_booru_artist_and_media_routes_keep_object_kinds_separate(url: str, kind: str) -> None:
    reference = recognize_url(url).reference
    assert reference is not None
    assert reference.object_kind == kind


def test_discovery_contract_validators_reject_unknown_values() -> None:
    assert validate_instance("BARAAG.NET") == "baraag.net"
    for function, value in (
        (validate_source_context, "account.password"),
        (validate_review_state, "accepted"),
        (validate_version, "v1"),
    ):
        with pytest.raises(ValueError):
            function(value)
    with pytest.raises(ValueError):
        validate_relation("same_work", candidate_kind="account")


def test_source_extractors_keep_context_and_json_paths() -> None:
    account = account_occurrences(
        {
            "account_id": 1,
            "account_snapshot_id": 2,
            "observed_at": "2026-08-06T00:00:00Z",
            "website_url": "https://example.test",
            "profile_url": None,
            "bio": "links https://pixiv.net/users/123 and https://x.com/name",
            "raw_observation_id": 3,
        }
    )
    assert [item.source_context for item in account] == [
        "account.website",
        "account.bio",
        "account.bio",
    ]
    raw = b'{"entities":{"urls":[{"expanded_url":"https://pixiv.net/artworks/9"}]}}'
    post = post_occurrences(
        {
            "post_id": 4,
            "canonical_url": None,
            "text_content": None,
            "observed_at": "2026-08-06T00:00:00Z",
            "raw_observation_id": 5,
        },
        raw,
    )
    assert post[0].source_context == "post.entity"
    assert post[0].json_path == "$.entities.urls[0].expanded_url"
    private = post_occurrences(
        {
            "post_id": 4,
            "canonical_url": None,
            "text_content": None,
            "observed_at": "2026-08-06T00:00:00Z",
            "raw_observation_id": 5,
        },
        b'{"private":{"url":"https://secret.example/reset?token=ABC"}}',
    )
    assert private == ()
