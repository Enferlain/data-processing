from __future__ import annotations

import json
from pathlib import Path


def test_public_fixture_is_metadata_only_and_keeps_user_variation_mapping() -> None:
    path = Path(__file__).parent / "fixtures" / "cross_platform_examples.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert fixture["media_fetched"] is False
    encoded = json.dumps(fixture)
    assert "pbs.twimg.com/media" not in encoded
    assert "i.pximg.net" not in encoded
    case = next(item for item in fixture["public_cases"] if item["case"] == 3)
    assert case["labels"]["variation_1_text"] == [
        "x:1837662117949800671",
        "danbooru:8186581",
        "gelbooru:10720246",
    ]
    assert case["labels"]["variation_1_no_text"] == ["gelbooru:10791439"]
    assert case["labels"]["variation_2"] == ["gelbooru:10791440"]
    assert case["labels_are_user_supplied"] is True
