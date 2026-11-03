"""Offline golden replay of the 2026-11-02 21-URL live validation batch.

Each fixture under tests/fixtures/golden_fetch/ holds one recorded raw payload
plus the normalized facts the live run persisted. The replay runs the REAL
fetch pipeline — resolver, shared adapter factory, adapter, sync service,
persistence — against a mock transport that serves the recorded payload and
refuses any request the live run did not make. This is the CI-side companion
to the live batch: wire-shape drift (wrapped envelopes, negative score
counts, naive timestamps) fails here before it can surprise a live run.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from media_catalog.cli import main
from media_catalog.database import CatalogDatabase

FIXTURES = Path(__file__).parent / "fixtures" / "golden_fetch"
SCENARIOS = sorted(FIXTURES.glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def golden(monkeypatch: pytest.MonkeyPatch):
    """Prepare one scenario's offline replay; returns run(scenario) -> context."""

    def run(scenario: dict) -> dict[str, object]:
        payload_bytes = json.dumps(scenario["payload"]).encode()
        served: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            served.append(request)
            if request.url.path == "/auth/token":
                # Sankaku replays the credential exchange with a dummy token;
                # tokens are never retained and never asserted.
                return httpx.Response(200, json={"success": True, "access_token": "replay-token"})
            extra_allowed = scenario["platform"] == "sankaku" and len(served) == 2
            if len(served) == 1 or extra_allowed:
                # Serve only the endpoint the live run hit, on that host.
                expected_host = (
                    "sankakuapi.com"
                    if scenario["platform"] == "sankaku"
                    else urlsplit(scenario["url"]).hostname
                )
                assert request.url.host == expected_host, request.url
                if scenario["platform"] == "sankaku":
                    assert request.headers.get("Authorization") == "Bearer replay-token"
                return httpx.Response(
                    200,
                    content=payload_bytes,
                    headers={"content-type": scenario["media_type"]},
                )
            raise AssertionError(f"unexpected extra request: {request.url}")

        real_client = httpx.Client

        def replay_client(*args: object, **kwargs: object) -> httpx.Client:
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(httpx, "Client", replay_client)
        for name in (
            "DANBOORU_LOGIN",
            "DANBOORU_API_KEY",
            "AIBOORU_LOGIN",
            "AIBOORU_API_KEY",
            "E621_USERNAME",
            "E621_API_KEY",
            "GELBOORU_USER_ID",
            "GELBOORU_API_KEY",
            "SANKAKU_LOGIN",
            "SANKAKU_PASSWORD",
        ):
            monkeypatch.delenv(name, raising=False)
        if scenario["platform"] == "sankaku":
            monkeypatch.setenv("SANKAKU_LOGIN", "replay-login")
            monkeypatch.setenv("SANKAKU_PASSWORD", "replay-password")
        return {"served": served}

    return run


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda path: path.stem)
def test_golden_fetch_replays_the_live_batch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    golden,
    path: Path,
) -> None:
    scenario = _load(path)
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass
    context = golden(scenario)

    main(["fetch", str(catalog), scenario["url"], "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "complete"
    assert payload["platform"] == scenario["platform"]
    assert payload["target"] == scenario["target"]
    if "canonical_url" in scenario:
        assert payload["canonical_url"] == scenario["canonical_url"]
    # Exactly the requests the live run made: the post fetch itself, plus the
    # sankaku credential exchange where that platform needs one.
    expected_requests = 2 if scenario["platform"] == "sankaku" else 1
    assert len(context["served"]) == expected_requests

    expect = scenario["expect"]
    with CatalogDatabase(catalog) as database:
        row = database.connection.execute(
            "SELECT po.native_post_id, p.platform_key,"
            " (SELECT count(*) FROM media_occurrences mo WHERE mo.post_id = po.post_id)"
            " AS media_occurrences"
            " FROM posts po JOIN platforms p ON p.platform_id = po.platform_id"
            " WHERE p.platform_key = ? AND po.native_post_id = ?",
            (expect["platform_key"], expect["native_post_id"]),
        ).fetchone()
    assert row is not None, "golden post must persist"
    assert tuple(row) == (
        expect["native_post_id"],
        expect["platform_key"],
        expect["media_occurrences"],
    )
    if "declared_md5" in expect:
        with CatalogDatabase(catalog) as database:
            md5 = database.connection.execute(
                "SELECT mo.declared_md5 FROM media_occurrences mo"
                " JOIN posts po USING(post_id) JOIN platforms p USING(platform_id)"
                " WHERE p.platform_key = ? AND po.native_post_id = ?"
                " AND mo.declared_md5 IS NOT NULL LIMIT 1",
                (expect["platform_key"], expect["native_post_id"]),
            ).fetchone()
        assert md5 is not None and md5[0] == expect["declared_md5"]
    if "score_down" in expect:
        with CatalogDatabase(catalog) as database:
            score = database.connection.execute(
                "SELECT o.score_down FROM post_metadata_observations o"
                " JOIN posts po USING(post_id) JOIN platforms p USING(platform_id)"
                " WHERE p.platform_key = ? AND po.native_post_id = ?"
                " ORDER BY o.post_metadata_observation_id DESC LIMIT 1",
                (expect["platform_key"], expect["native_post_id"]),
            ).fetchone()
        # Negative counts are valid live wire (e621 family); the replay must
        # preserve them verbatim instead of clamping.
        assert score is not None and score[0] == expect["score_down"]


def test_golden_fixture_directory_holds_the_full_batch() -> None:
    platforms = [_load(path)["platform"] for path in SCENARIOS]
    assert len(SCENARIOS) == 21
    assert {platform: platforms.count(platform) for platform in set(platforms)} == {
        "danbooru": 6,
        "e621": 6,
        "sankaku": 6,
        "pawchive": 3,
    }
