from __future__ import annotations

import pytest

from media_catalog.adapters.gelbooru import (
    DAPI_SCHEMA_VERSION,
    DAPI_TRANSPORT_VERSION,
    GELBOORU,
    HTML_PARSER_VERSION,
    HTML_SCHEMA_VERSION,
    MAX_PAGE_SIZE,
    MINIMUM_INTERVAL_SECONDS,
    GelbooruCredentials,
    GelbooruInstance,
    GelbooruTransport,
)


def test_gelbooru_transport_versions_are_explicit_and_independent() -> None:
    assert set(GelbooruTransport) == {
        GelbooruTransport.DAPI_JSON,
        GelbooruTransport.HTML_POST,
    }
    assert GELBOORU.schema_version(GelbooruTransport.DAPI_JSON) == DAPI_SCHEMA_VERSION
    assert GELBOORU.schema_version(GelbooruTransport.HTML_POST) == HTML_SCHEMA_VERSION
    assert GELBOORU.transport_version(GelbooruTransport.DAPI_JSON) == DAPI_TRANSPORT_VERSION
    assert GELBOORU.transport_version(GelbooruTransport.HTML_POST) == HTML_PARSER_VERSION
    assert DAPI_SCHEMA_VERSION != HTML_SCHEMA_VERSION


def test_provider_policy_cannot_be_weakened_or_redirected() -> None:
    with pytest.raises(ValueError, match="canonical HTTPS"):
        GelbooruInstance(base_url="http://gelbooru.com")
    with pytest.raises(ValueError, match="canonical HTTPS"):
        GelbooruInstance(base_url="https://attacker.example")
    with pytest.raises(ValueError, match="minimum interval"):
        GelbooruInstance(minimum_interval_seconds=MINIMUM_INTERVAL_SECONDS - 0.1)
    with pytest.raises(ValueError, match="page size"):
        GelbooruInstance(page_size=MAX_PAGE_SIZE + 1)
    with pytest.raises(ValueError, match="page size"):
        GelbooruInstance(page_size=0)
    with pytest.raises(ValueError, match="response and time"):
        GelbooruInstance(max_response_bytes=0)
    with pytest.raises(ValueError, match="response and time"):
        GelbooruInstance(request_timeout_seconds=0)


def test_credentials_are_external_complete_and_redacted() -> None:
    for environ in ({}, {GELBOORU.user_id_env: "123"}, {GELBOORU.api_key_env: "secret"}):
        with pytest.raises(ValueError, match="configure both"):
            GelbooruCredentials.from_environment(GELBOORU, environ)

    credentials = GelbooruCredentials.from_environment(
        GELBOORU,
        {GELBOORU.user_id_env: "123", GELBOORU.api_key_env: "sentinel-secret"},
    )
    assert credentials.user_id == "123"
    assert credentials.api_key == "sentinel-secret"
    assert "123" not in repr(credentials)
    assert "sentinel-secret" not in repr(credentials)


def test_credentials_reject_control_characters() -> None:
    with pytest.raises(ValueError, match="control"):
        GelbooruCredentials("123", "secret\nvalue")
