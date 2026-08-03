import pytest

from x_likes.provider import ProviderError, ProviderUnavailable, normalize_fxtwitter


def test_normalizes_fxtwitter_v2_payload():
    payload = {
        "code": 200,
        "message": "OK",
        "tweet": {
            "id": "123",
            "url": "https://x.com/person/status/123",
            "text": "post text",
            "created_at": "Fri Aug 01 12:00:00 +0000 2025",
            "author": {
                "id": "7",
                "name": "Person",
                "screen_name": "person",
                "description": "A useful bio",
                "url": "https://x.com/person",
                "avatar_url": "https://pbs.twimg.com/profile_images/person.jpg",
                "banner_url": "https://pbs.twimg.com/profile_banners/7/banner.jpg",
                "location": "Somewhere",
                "website": {"url": "https://example.com", "display_url": "example.com"},
                "followers": 120,
                "following": 30,
                "verification": {"verified": True, "type": "individual"},
            },
            "media": {
                "photos": [
                    {
                        "url": "https://pbs.twimg.com/media/example.jpg",
                        "width": 1200,
                        "height": 800,
                        "altText": "Example image",
                    }
                ]
            },
        },
    }

    result = normalize_fxtwitter(payload, expected_post_id="123")

    assert result.author_handle == "person"
    assert result.author_name == "Person"
    assert result.account is not None
    assert result.account.bio == "A useful bio"
    assert result.account.website_url == "https://example.com"
    assert result.account.followers == 120
    assert result.account.verified is True
    assert result.account.verification_type == "individual"
    assert result.images[0].alt_text == "Example image"
    assert result.images[0].width == 1200


def test_normalizes_current_status_payload():
    payload = {
        "code": 200,
        "status": {
            "type": "status",
            "id": "20",
            "url": "https://x.com/jack/status/20",
            "text": "just setting up my twttr",
            "author": {
                "id": "12",
                "name": "jack",
                "screen_name": "jack",
                "description": "",
            },
            "media": {},
        },
    }

    result = normalize_fxtwitter(payload, expected_post_id="20")

    assert result.post_id == "20"
    assert result.author_handle == "jack"
    assert result.account is not None
    assert result.account.bio == ""


def test_normalizes_scalar_website_and_flat_verification():
    payload = {
        "code": 200,
        "status": {
            "type": "status",
            "id": "123",
            "author": {
                "id": "7",
                "website": "https://example.com",
                "verified": "false",
            },
        },
    }

    result = normalize_fxtwitter(payload, expected_post_id="123")

    assert result.account is not None
    assert result.account.website_url == "https://example.com"
    assert result.account.verified is False


def test_rejects_payload_without_tweet():
    with pytest.raises(ProviderError, match="private"):
        normalize_fxtwitter({"code": 404, "message": "private"}, expected_post_id="123")


def test_preserves_tombstone_reason():
    payload = {
        "code": 404,
        "status": {
            "type": "tombstone",
            "reason": "deleted",
            "message": "This post was deleted",
            "id": "123",
        },
    }

    with pytest.raises(ProviderUnavailable, match="deleted") as raised:
        normalize_fxtwitter(payload, expected_post_id="123")

    assert raised.value.reason == "deleted"
    assert raised.value.raw == payload
