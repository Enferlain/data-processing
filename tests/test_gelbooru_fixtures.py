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


def test_dapi_fixture_suite_shape_and_manifest() -> None:
    suite = _dapi_suite()
    assert suite.manifest.provider == "gelbooru"
    assert suite.manifest.instance == "gelbooru"
    assert suite.manifest.adapter_version == ADAPTER_VERSION
    assert suite.manifest.schema_version == DAPI_SCHEMA_VERSION
    assert suite.manifest.redactions
    assert [case.name for case in suite.cases] == [
        "post_12370900",
        "post_11605534",
        "variation_distinct_10720246",
        "variation_pair_10791439",
        "variation_pair_10791440",
    ]
    assert all(case.operation.value == "fetch_post" for case in suite.cases)


def test_dapi_expected_summaries_match_captured_bodies() -> None:
    for case in _dapi_suite().cases:
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
    assert [case.target for case in suite.cases] == [case.target for case in _dapi_suite().cases]
    assert all(case.request_identity.startswith("gelbooru:html_post:") for case in suite.cases)


def test_html_bodies_preserve_markers_without_scripts_or_session_tokens() -> None:
    for case in _html_suite().cases:
        body = json.loads(case.response.payload)
        assert "tag-type-artist" in body, case.name
        assert {"artist", "general"} <= set(case.expected["tag_categories"]), case.name
        assert "Posted:" in body and "Uploader:" in body, case.name
        assert 'id="image"' in body, case.name
        assert case.expected["uploader"], case.name
        assert case.expected["post_ids"] == [case.target]
        assert "<script" not in body, case.name
        assert not re.search(r"csrf-token=[0-9a-f]", body), case.name
