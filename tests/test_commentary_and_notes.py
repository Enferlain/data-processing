"""Commentary and notes enrichment tests (OpenSpec add-commentary-and-notes).

Opt-in enrichment never touches default sync: an operator fetches one
retained post's commentary or notes; observations are digest-deduplicated
over the text facts; empty results are successful empty sets; every run
follows the bounded run contract (raw retained for every response, provider
faults end failed, transport errors leave an auditable run).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest

from media_catalog.adapters import AdapterOperation, AdapterRequest, ResponseEnvelope
from media_catalog.adapters.danbooru.adapter import DanbooruAdapter
from media_catalog.adapters.danbooru.config import DANBOORU
from media_catalog.adapters.e621.adapter import E621Adapter
from media_catalog.adapters.e621.config import E621
from media_catalog.adapters.gelbooru.adapter import GelbooruAdapter
from media_catalog.adapters.gelbooru.config import GELBOORU
from media_catalog.adapters.gelbooru.credentials import GelbooruCredentials
from media_catalog.database import CatalogDatabase
from media_catalog.remote_sync.enrichment import fetch_commentary, fetch_notes

FIXTURES = Path(__file__).parent / "fixtures" / "metadata_adapters"


class _StubAdapter:
    def __init__(
        self,
        *,
        platform: str = "danbooru",
        payload: bytes,
        status_code: int = 200,
        operation: AdapterOperation = AdapterOperation.FETCH_COMMENTARY,
    ) -> None:
        self.instance_key = platform
        self.adapter_version = "test-v1"
        self.schema_version = "test-v1"
        self._payload = payload
        self._status = status_code
        self._operation = operation

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        assert request.operation is self._operation
        return ResponseEnvelope(
            provider=self.instance_key,
            instance=self.instance_key,
            operation=request.operation,
            request_identity=f"{self.instance_key}:{request.operation.value}:{request.target}",
            status_code=self._status,
            headers={"content-type": "application/json"},
            payload=self._payload,
            observed_at="2026-10-24T00:00:00Z",
            adapter_version="test-v1",
            schema_version="test-v1",
        )


def _seed(catalog: Path, *, platform: str, natives: tuple[str, ...]) -> None:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        connection.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name) VALUES (?, ?)",
            (platform, platform.capitalize()),
        )
        platform_id = int(
            connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = ?", (platform,)
            ).fetchone()[0]
        )
        for native in natives:
            connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, first_seen_at, last_seen_at)
                   VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (platform_id, native),
            )
        connection.commit()


def _commentary_payload() -> bytes:
    return (FIXTURES / "danbooru_commentary_12436862.json").read_bytes()


def _e621_notes_payload() -> bytes:
    return (FIXTURES / "e621_notes_6623509.json").read_bytes()


def _gelbooru_notes_payload() -> bytes:
    # The fixture is the modern dapi wrapper; the parser unwraps "note".
    return (FIXTURES / "gelbooru_notes_953320_SYNTHETIC.json").read_bytes()


def test_commentary_lands_with_the_artist_caption(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog, platform="danbooru", natives=("12436862",))
    with CatalogDatabase(catalog) as database:
        report = fetch_commentary(
            database, _StubAdapter(payload=_commentary_payload()), "12436862", clock=_now
        )
        connection = database.connection
        assert report["outcome"] == "success"
        assert report["observations"] == 1
        row = connection.execute(
            """SELECT original_title, original_description, translated_title,
                      translated_description FROM post_commentary_observations"""
        ).fetchone()
        assert row["original_title"].startswith("PIXIV")
        assert "ディッコです" in row["original_description"]
        assert row["translated_title"] is None
        raw = connection.execute(
            "SELECT object_kind, native_id, status FROM raw_observations "
            "WHERE object_kind = 'commentary'"
        ).fetchone()
        assert raw["native_id"] == "12436862" and raw["status"] == "200"
        run = connection.execute(
            "SELECT status, termination_outcome, record_count FROM remote_runs"
        ).fetchone()
        assert (run["status"], run["termination_outcome"], run["record_count"]) == (
            "complete",
            "success",
            1,
        )


def test_commentary_absence_is_a_successful_empty_set(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog, platform="danbooru", natives=("8001",))
    with CatalogDatabase(catalog) as database:
        report = fetch_commentary(database, _StubAdapter(payload=b"[]"), "8001", clock=_now)
        connection = database.connection
        assert report["outcome"] == "success"
        assert report["observations"] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM post_commentary_observations").fetchone()[0]
            == 0
        )
        # Absence still retains the (empty) response and a successful run.
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM raw_observations WHERE object_kind = 'commentary'"
            ).fetchone()[0]
            == 1
        )


def test_commentary_edit_lands_as_a_new_observation(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog, platform="danbooru", natives=("12436862",))
    with CatalogDatabase(catalog) as database:
        fetch_commentary(
            database, _StubAdapter(payload=_commentary_payload()), "12436862", clock=_now
        )
        edited = _commentary_payload().replace(
            b"\xe3\x83\x87\xe3\x82\xa3\xe3\x83\x83\xe3\x82\xb3", b"EDITED"
        )
        second = fetch_commentary(database, _StubAdapter(payload=edited), "12436862", clock=_now)
        connection = database.connection
        assert second["outcome"] == "success"
        assert (
            connection.execute("SELECT COUNT(*) FROM post_commentary_observations").fetchone()[0]
            == 2
        )
        assert (
            "EDITED"
            in connection.execute(
                "SELECT original_description FROM post_commentary_observations "
                "ORDER BY post_commentary_observation_id DESC LIMIT 1"
            ).fetchone()[0]
        )
        # Unchanged text re-observed at another time dedups by digest.
        third = fetch_commentary(database, _StubAdapter(payload=edited), "12436862", clock=_now)
        assert third["observations"] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM post_commentary_observations").fetchone()[0]
            == 2
        )


def test_notes_land_with_position_and_version(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog, platform="e621", natives=("6623509",))
    with CatalogDatabase(catalog) as database:
        report = fetch_notes(
            database,
            _StubAdapter(
                platform="e621",
                payload=_e621_notes_payload(),
                operation=AdapterOperation.FETCH_NOTES,
            ),
            "6623509",
            clock=_now,
        )
        connection = database.connection
        assert report["observations"] == 1
        row = connection.execute(
            """SELECT note_native_id, body, position_x, position_y, width, height, version
                 FROM post_note_observations"""
        ).fetchone()
        assert (row["note_native_id"], row["version"]) == ("510059", 2)
        assert row["body"] == "もいち(moichi)"
        assert (row["position_x"], row["position_y"], row["width"], row["height"]) == (
            58,
            3638,
            316,
            160,
        )


def test_gelbooru_notes_land_and_an_edit_bumps_the_row(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog, platform="gelbooru", natives=("953320",))
    with CatalogDatabase(catalog) as database:
        first = fetch_notes(
            database,
            _StubAdapter(
                platform="gelbooru",
                payload=_gelbooru_notes_payload(),
                operation=AdapterOperation.FETCH_NOTES,
            ),
            "953320",
            clock=_now,
        )
        connection = database.connection
        assert first["observations"] == 2
        rows = connection.execute(
            "SELECT note_native_id, version FROM post_note_observations ORDER BY note_native_id"
        ).fetchall()
        assert [(row["note_native_id"], row["version"]) for row in rows] == [
            ("1900001", None),
            ("1900002", None),
        ]
        # A moved note lands as a new observation for the same note id.
        moved = _gelbooru_notes_payload().replace(b'"x": 120', b'"x": 999')
        fetch_notes(
            database,
            _StubAdapter(
                platform="gelbooru", payload=moved, operation=AdapterOperation.FETCH_NOTES
            ),
            "953320",
            clock=_now,
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM post_note_observations WHERE note_native_id = '1900001'"
            ).fetchone()[0]
            == 2
        )


def test_unknown_post_is_refused_before_any_run(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog, platform="danbooru", natives=("12436862",))
    with CatalogDatabase(catalog) as database:
        with pytest.raises(ValueError, match="no retained danbooru post"):
            fetch_commentary(
                database, _StubAdapter(payload=_commentary_payload()), "99999999", clock=_now
            )
        assert database.connection.execute("SELECT COUNT(*) FROM remote_runs").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("status_code", "payload", "outcome"),
    [
        (404, b"[]", "unavailable"),
        (200, b"not json", "malformed_response"),
        (200, b'{"object": true}', "malformed_response"),
    ],
)
def test_failure_outcomes_are_typed_and_raw_is_retained(
    tmp_path: Path, status_code: int, payload: bytes, outcome: str
) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog, platform="danbooru", natives=("12436862",))
    with CatalogDatabase(catalog) as database:
        report = fetch_commentary(
            database,
            _StubAdapter(payload=payload, status_code=status_code),
            "12436862",
            clock=_now,
        )
        connection = database.connection
        assert report["outcome"] == outcome
        assert report["observations"] == 0
        run = connection.execute("SELECT status, termination_outcome FROM remote_runs").fetchone()
        assert (run["status"], run["termination_outcome"]) == ("failed", outcome)
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM raw_observations WHERE object_kind = 'commentary'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM post_commentary_observations").fetchone()[0]
            == 0
        )


def test_transport_failure_leaves_an_auditable_run(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog, platform="danbooru", natives=("12436862",))

    class _Raising(_StubAdapter):
        def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
            raise RuntimeError("transport exploded")

    with CatalogDatabase(catalog) as database:
        with pytest.raises(RuntimeError, match="transport exploded"):
            fetch_commentary(database, _Raising(payload=b"[]"), "12436862", clock=_now)
        run = database.connection.execute(
            "SELECT status, termination_outcome, request_count FROM remote_runs"
        ).fetchone()
        assert (run["status"], run["termination_outcome"], run["request_count"]) == (
            "failed",
            "local_persistence",
            0,
        )


def test_commentary_and_note_observations_are_storage_immutable(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog, platform="danbooru", natives=("12436862",))
    with CatalogDatabase(catalog) as database:
        fetch_commentary(
            database, _StubAdapter(payload=_commentary_payload()), "12436862", clock=_now
        )
        fetch_notes(
            database,
            _StubAdapter(
                platform="danbooru",
                payload=_e621_notes_payload(),
                operation=AdapterOperation.FETCH_NOTES,
            ),
            "12436862",
            clock=_now,
        )
        for statement in (
            "UPDATE post_commentary_observations SET original_title = 'x'",
            "DELETE FROM post_commentary_observations",
            "UPDATE post_note_observations SET body = 'x'",
            "DELETE FROM post_note_observations",
        ):
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                database.connection.execute(statement)


def test_adapters_request_the_documented_endpoints() -> None:
    requested: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        requested[str(request.url)] = request.url.params.get("search[post_id]") or ""
        return httpx.Response(200, content=b"[]")

    transport = httpx.MockTransport(handler)
    danbooru = DanbooruAdapter(DANBOORU, client=httpx.Client(transport=transport))
    envelope = danbooru.fetch(
        AdapterRequest(operation=AdapterOperation.FETCH_COMMENTARY, target="12436862")
    )
    assert envelope.status_code == 200
    assert "/artist_commentaries.json" in next(iter(requested))
    assert requested[next(iter(requested))] == "12436862"

    e621 = E621Adapter(E621, client=httpx.Client(transport=transport))
    e621.fetch(AdapterRequest(operation=AdapterOperation.FETCH_NOTES, target="6623509"))
    e621_url = next(url for url in requested if "/notes.json" in url)
    assert requested[e621_url] == "6623509"

    gelbooru = GelbooruAdapter(
        GELBOORU,
        client=httpx.Client(transport=transport),
        credentials=GelbooruCredentials("1", "k"),
    )
    gelbooru.fetch(AdapterRequest(operation=AdapterOperation.FETCH_NOTES, target="953320"))
    gelbooru_url = next(url for url in requested if "s=note" in url)
    assert "post_id=953320" in gelbooru_url


def _now() -> str:
    return "2026-10-24T00:00:00Z"


def test_all_empty_commentary_is_absence_not_a_crash(tmp_path: Path) -> None:
    """Review regression: providers create commentary rows with every field
    empty; absence must not raise mid-transaction (which would leave a
    zombie running run and lose the raw report)."""

    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog, platform="danbooru", natives=("8002",))
    empty = (
        b'[{"id": 101, "post_id": 8002, "original_title": "", '
        b'"original_description": "", "translated_title": "", '
        b'"translated_description": ""}]'
    )
    with CatalogDatabase(catalog) as database:
        report = fetch_commentary(database, _StubAdapter(payload=empty), "8002", clock=_now)
        connection = database.connection
        assert report["outcome"] == "success"
        assert report["observations"] == 0
        run = connection.execute("SELECT status, termination_outcome FROM remote_runs").fetchone()
        assert (run["status"], run["termination_outcome"]) == ("complete", "success")
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM raw_observations WHERE object_kind = 'commentary'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    ("payload", "platform", "operation"),
    [
        (
            b'[{"id": 1, "post_id": 999, "original_title": "x"}]',
            "danbooru",
            AdapterOperation.FETCH_COMMENTARY,
        ),
        (
            b'[{"id": 5, "body": "ok", "x": -5}]',
            "e621",
            AdapterOperation.FETCH_NOTES,
        ),
        (b'[{"id": 5, "body": "ok"}, {"id": 6}]', "e621", AdapterOperation.FETCH_NOTES),
    ],
)
def test_contract_violations_classify_malformed_without_zombie_runs(
    tmp_path: Path, payload: bytes, platform: str, operation: AdapterOperation
) -> None:
    """Review regression: strict parsing classifies the whole document, so
    no record constructor raises inside the transaction."""

    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog, platform=platform, natives=("1",))
    with CatalogDatabase(catalog) as database:
        if operation is AdapterOperation.FETCH_COMMENTARY:
            report = fetch_commentary(database, _StubAdapter(payload=payload), "1", clock=_now)
        else:
            report = fetch_notes(
                database,
                _StubAdapter(platform=platform, payload=payload, operation=operation),
                "1",
                clock=_now,
            )
        connection = database.connection
        assert report["outcome"] == "malformed_response"
        run = connection.execute("SELECT status, termination_outcome FROM remote_runs").fetchone()
        assert (run["status"], run["termination_outcome"]) == ("failed", "malformed_response")
        assert connection.execute("SELECT COUNT(*) FROM post_note_observations").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM post_commentary_observations").fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 1


def test_gelbooru_legacy_bare_array_still_parses(tmp_path: Path) -> None:
    """The parser accepts both the modern dapi wrapper and a bare array."""

    catalog = tmp_path / "catalog.sqlite3"
    _seed(catalog, platform="gelbooru", natives=("953320",))
    bare = b'[{"id": 1900001, "post_id": 953320, "x": 1, "y": 2, "body": "legacy"}]'
    with CatalogDatabase(catalog) as database:
        report = fetch_notes(
            database,
            _StubAdapter(platform="gelbooru", payload=bare, operation=AdapterOperation.FETCH_NOTES),
            "953320",
            clock=_now,
        )
        assert report["outcome"] == "success"
        assert report["observations"] == 1


@pytest.mark.parametrize(
    ("command", "native", "platform"),
    [
        ("danbooru-commentary", "12436862", "danbooru"),
        ("aibooru-commentary", "12436862", "danbooru"),
        ("gelbooru-dapi-notes", "953320", "gelbooru"),
        ("e621-notes", "6623509", "e621"),
        ("danbooru-pool", "17001", "danbooru"),
    ],
)
def test_enrichment_commands_route_to_their_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    native: str,
    platform: str,
) -> None:
    """Review regression: the gelbooru-/e621- prefix branches shadowed the
    notes commands before the exact-match branch was hoisted above them."""

    import media_catalog.cli as cli_module
    from media_catalog.cli import main

    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass

    calls: list[tuple[str, str]] = []

    def _fake(surface: str):
        def run(database, adapter, target, **kwargs):
            calls.append((surface, str(target)))
            return {"remote_run_id": 1, "outcome": "success", "observations": 0}

        return run

    class _FakeCreds:
        @classmethod
        def from_environment(cls, instance: object) -> object:
            return object()

    class _FakeAdapter:
        def __init__(self, instance: object, *, client: object, credentials: object = None):
            pass

    monkeypatch.setattr(cli_module, "fetch_commentary", _fake("commentary"))
    monkeypatch.setattr(cli_module, "fetch_notes", _fake("notes"))
    monkeypatch.setattr(cli_module, "fetch_pool", _fake("pool"))
    monkeypatch.setattr(cli_module, "DanbooruCredentials", _FakeCreds)
    monkeypatch.setattr(cli_module, "GelbooruCredentials", _FakeCreds)
    monkeypatch.setattr(cli_module, "E621Credentials", _FakeCreds)
    monkeypatch.setattr(cli_module, "DanbooruAdapter", _FakeAdapter)
    monkeypatch.setattr(cli_module, "GelbooruAdapter", _FakeAdapter)
    monkeypatch.setattr(cli_module, "E621Adapter", _FakeAdapter)

    main(["metadata", command, str(catalog), native, "--json"])

    surface = (
        "pool"
        if command.endswith("-pool")
        else ("commentary" if command.endswith("-commentary") else "notes")
    )
    assert calls == [(surface, native)]
