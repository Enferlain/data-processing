"""Offline golden replay of the 2026-11-05 bare-file discovery run (session 32).

The fixture holds the recorded wire payloads for every provider the live run
touched: three generation-zero hash queries (one 429, two zero-result
successes, one hit), plus the wave-A fetch of the hit post.  The replay runs
the REAL discovery pipeline — file seed materialization, planner, provider
lookups, follow-up generation — over a transport that serves the recorded
responses by host and query shape and refuses anything unrecorded.  Wire or
planner drift in the bare-file path fails here before a live run can be
surprised.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from media_catalog.cli import main
from media_catalog.database import CatalogDatabase

FIXTURE = Path(__file__).parent / "fixtures" / "golden_discover" / "c415b9ca_file_discovery.json"


@pytest.fixture()
def image_file(tmp_path: Path):
    """A byte file whose recorded md5 the seed machinery recomputes; contents
    are opaque — identity comes from the hash the live file carried."""
    scenario = json.loads(FIXTURE.read_text(encoding="utf-8"))
    path = tmp_path / "picked.jpg"
    # Any bytes hash deterministically; the recorded md5 pins the expectation
    # that the planner plans verified_md5, not that these bytes match the
    # original image (the provider responses are what decide hits).
    path.write_bytes(b"golden-discovery-replay" * 16)
    scenario["_replay_md5"] = __import__("hashlib").md5(path.read_bytes()).hexdigest()
    return path, scenario


def _response_for(request: httpx.Request, scenario: dict, seen: list) -> httpx.Response:
    seen.append(str(request.url))
    recorded = scenario["provider_responses"]
    host = request.url.host
    raw_query = request.url.query
    query = parse_qs(raw_query.decode() if isinstance(raw_query, bytes) else raw_query)
    if host == "danbooru.donmai.us":
        rate = recorded["danbooru"]
        return httpx.Response(int(rate["status"]), headers={"retry-after": rate["retry_after"]})
    if host == "aibooru.online":
        body = recorded["aibooru"]
        return httpx.Response(
            200, content=body["payload"].encode(), headers={"content-type": body["media_type"]}
        )
    if host == "e621.net":
        body = recorded["e621"]
        return httpx.Response(
            200, content=body["payload"].encode(), headers={"content-type": body["media_type"]}
        )
    if host in {"gelbooru.com", "www.gelbooru.com"}:
        if any("md5" in value for values in query.values() for value in values):
            body = recorded["gelbooru_md5_query"]
        else:
            body = recorded["gelbooru_post_fetch"]
        return httpx.Response(
            200, content=body["payload"].encode(), headers={"content-type": body["media_type"]}
        )
    raise AssertionError(f"unrecorded host: {request.url}")


def test_golden_bare_file_discovery_replays_the_live_session(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    image_file,
) -> None:
    path, scenario = image_file
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass

    real_client = httpx.Client
    seen_requests: list[str] = []
    scenario = dict(scenario)
    scenario["_seen"] = seen_requests

    def replay_client(*args: object, **kwargs: object) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(
            lambda request: _response_for(request, scenario, seen_requests)
        )
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "Client", replay_client)
    for name in (
        "GELBOORU_USER_ID",
        "GELBOORU_API_KEY",
        "E621_USERNAME",
        "E621_API_KEY",
        "DANBOORU_LOGIN",
        "DANBOORU_API_KEY",
        "AIBOORU_LOGIN",
        "AIBOORU_API_KEY",
        "SANKAKU_LOGIN",
        "SANKAKU_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GELBOORU_USER_ID", "replay-user")
    monkeypatch.setenv("GELBOORU_API_KEY", "replay-key")

    main(
        [
            "discover",
            str(catalog),
            "--file",
            str(path),
            "--live",
            "--max-requests",
            "16",
            "--max-seconds",
            "120",
            "--json",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    expect = scenario["expect"]
    assert report["input_kind"] == expect["input_kind"]
    assert report["file_seed"]["verified_md5"] == scenario["_replay_md5"]
    # The seed's computed hash must drive the provider query itself.
    gelbooru_md5_queries = [
        url for url in seen_requests if "gelbooru" in url and scenario["_replay_md5"] in url
    ]
    assert gelbooru_md5_queries, seen_requests
    gen0 = {
        (step["source"], step["method"]): step
        for step in report["steps"]
        if step["source_kind"] == "provider"
    }
    for provider, pinned in expect["generation_zero"].items():
        step = gen0[(provider, "verified_md5")]
        assert step["status"] == pinned["status"], (provider, step)
        if "result_count" in pinned:
            assert (step["result_count"] or 0) == pinned["result_count"], provider
    # The hit fans out: exactly one wave-A fetch of the provider-native post.
    generations = report.get("generations", [])
    wave_a = [
        step
        for generation in generations
        for step in generation["steps"]
        if generation["generation"] == 1 and step["method"] == "fetch_post"
    ]
    assert len(wave_a) == 1
    fetch = wave_a[0]
    assert (fetch["source"], fetch["target"], fetch["status"]) == (
        expect["wave_a"]["source"],
        expect["wave_a"]["target"],
        expect["wave_a"]["status"],
    )
    # The fetched post persisted with its native identity.
    with CatalogDatabase(catalog) as database:
        row = database.connection.execute(
            """SELECT po.native_post_id FROM posts po
                 JOIN platforms p ON p.platform_id = po.platform_id
                WHERE p.platform_key = ? AND po.native_post_id = ?""",
            (expect["wave_a"]["source"], expect["wave_a"]["target"]),
        ).fetchone()
    assert row is not None, "hit post must persist"
