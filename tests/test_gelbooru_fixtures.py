from __future__ import annotations

import json
import re
from pathlib import Path

from media_catalog.adapters.fixtures import load_fixture_suite
from media_catalog.adapters.gelbooru import (
    ADAPTER_VERSION,
    DAPI_SCHEMA_VERSION,
    HTML_SCHEMA_VERSION,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"


def _dapi_suite():
    return load_fixture_suite(FIXTURES / "gelbooru.json")


def _html_suite():
    return load_fixture_suite(FIXTURES / "gelbooru_html.json")


POST_CASES = [
    "post_12370900",
    "post_11605534",
    "variation_distinct_10720246",
    "variation_pair_10791439",
    "variation_pair_10791440",
]


def test_dapi_fixture_suite_shape_and_manifest() -> None:
    suite = _dapi_suite()
    assert suite.manifest.provider == "gelbooru"
    assert suite.manifest.instance == "gelbooru"
    assert suite.manifest.adapter_version == ADAPTER_VERSION
    assert suite.manifest.schema_version == DAPI_SCHEMA_VERSION
    assert suite.manifest.redactions
    assert [case.name for case in suite.cases] == [
        *POST_CASES,
        "tag_metadata",
        "post_typed_tags_parent_title_synth",
        "post_not_found",
        "authentication_required",
        "authorization_denied",
        "transient_provider",
        "error_envelope",
        "response_oversized",
        "malformed_json",
    ]
    operations = {case.name: case.operation.value for case in suite.cases}
    assert operations["tag_metadata"] == "fetch_tag"
    assert operations["post_12370900"] == "fetch_post"


def test_dapi_expected_summaries_match_captured_bodies() -> None:
    by_name = {case.name: case for case in _dapi_suite().cases}
    for name in POST_CASES:
        case = by_name[name]
        body = json.loads(case.response.payload)
        post = body["post"][0]
        assert case.expected["post_ids"] == [str(post["id"])]
        assert case.expected["declared_md5"] == post["md5"]
        assert case.expected["width"] == post["width"]
        assert case.expected["height"] == post["height"]
        assert case.expected["rating"] == post["rating"]
        assert case.expected["owner"] == post["owner"]
        assert case.expected["tag_count"] == len(post["tags"].split())
        assert "file" in case.expected["variants"] and "preview" in case.expected["variants"]
        assert case.request_identity == f"gelbooru:dapi_json:post:{case.target}"


def test_variation_trio_matches_the_documented_examples() -> None:
    """docs/plans/test_list.md: one image with and without text, one different from both."""
    expected = {case.name: case.expected for case in _dapi_suite().cases}
    pair_a = expected["variation_pair_10791439"]
    pair_b = expected["variation_pair_10791440"]
    distinct = expected["variation_distinct_10720246"]

    assert (pair_a["width"], pair_a["height"]) == (pair_b["width"], pair_b["height"])
    assert pair_a["declared_md5"] != pair_b["declared_md5"]
    assert (distinct["width"], distinct["height"]) != (pair_a["width"], pair_a["height"])


def test_html_fixture_suite_shape_and_manifest() -> None:
    suite = _html_suite()
    assert suite.manifest.provider == "gelbooru"
    assert suite.manifest.schema_version == HTML_SCHEMA_VERSION
    assert suite.manifest.adapter_version == ADAPTER_VERSION
    dapi_targets = [case.target for case in _dapi_suite().cases][: len(POST_CASES)]
    assert [case.target for case in suite.cases][: len(POST_CASES)] == dapi_targets
    assert {case.name for case in suite.cases} >= {
        "html_not_found",
        "html_challenge",
        "html_malformed",
    }
    assert all(case.request_identity.startswith("gelbooru:html_post:") for case in suite.cases)


def test_html_bodies_preserve_markers_without_scripts_or_session_tokens() -> None:
    by_name = {case.name: case for case in _html_suite().cases}
    for case in list(by_name.values())[: len(POST_CASES)]:
        body = json.loads(case.response.payload)
        assert "tag-type-artist" in body, case.name
        assert {"artist", "general"} <= set(case.expected["tag_categories"]), case.name
        assert "Posted:" in body and "Uploader:" in body, case.name
        assert 'id="image"' in body, case.name
        assert case.expected["uploader"], case.name
        assert case.expected["post_ids"] == [case.target]
        assert "<script" not in body, case.name
        assert not re.search(r"csrf-token=[0-9a-f]", body), case.name


def test_error_and_tag_cases_pin_typed_outcomes() -> None:
    expected = {case.name: case.expected for case in _dapi_suite().cases}
    assert expected["tag_metadata"]["outcome"] == "success"
    assert expected["tag_metadata"]["names"] == ["hiroki_(yyqw7151)"]
    assert expected["tag_metadata"]["native_types"] == [1]
    assert expected["post_not_found"]["outcome"] == "unavailable"
    assert expected["authentication_required"]["outcome"] == "authentication_required"
    assert expected["authorization_denied"]["outcome"] == "authorization_denied"
    assert expected["transient_provider"]["outcome"] == "transient_provider"
    assert expected["error_envelope"]["outcome"] == "malformed_response"
    assert expected["response_oversized"]["outcome"] == "response_too_large"
    assert expected["malformed_json"]["outcome"] == "malformed_response"

    html_expected = {case.name: case.expected for case in _html_suite().cases}
    assert html_expected["html_not_found"]["outcome"] == "unavailable"
    assert html_expected["html_challenge"]["outcome"] == "authorization_denied"
    assert html_expected["html_malformed"]["outcome"] == "malformed_response"


def test_not_found_and_tag_bodies_match_observed_shapes() -> None:
    cases = {case.name: case for case in _dapi_suite().cases}

    missing = json.loads(cases["post_not_found"].response.payload)
    assert cases["post_not_found"].response.status_code == 200
    assert missing["@attributes"]["count"] == 0
    assert "post" not in missing

    auth = cases["authentication_required"]
    assert auth.response.status_code == 401
    assert json.loads(auth.response.payload) == ""

    tag_body = json.loads(cases["tag_metadata"].response.payload)
    assert tag_body["tag"][0]["name"] == "hiroki_(yyqw7151)"
    assert set(tag_body["tag"][0]) == {"id", "name", "count", "type", "ambiguous"}
