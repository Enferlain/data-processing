from __future__ import annotations

import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import httpx
import pytest

import media_catalog.labeling.remote as remote
from media_catalog.database import CatalogDatabase
from media_catalog.labeling.remote import RemoteMediaError, fetch_remote_media
from media_catalog.labeling.sankaku import SankakuDisplayResolver
from media_catalog.labeling.server import LabelingState, create_server

NOW = "2026-11-07T22:00:00Z"
URL = "https://img4.gelbooru.com/images/test.jpg"
SANKAKU_POST = "78MYwlekbre"
SANKAKU_FRESH = "https://v.sankakucomplex.com/data/fresh.jpg?expires=4102444800&token=fresh"


@pytest.fixture
def database(tmp_path):
    with CatalogDatabase(tmp_path / "catalog.sqlite3") as db:
        c = db.connection
        c.execute(
            "INSERT OR IGNORE INTO platforms(platform_key,display_name) VALUES('gelbooru','G')"
        )
        c.execute(
            """INSERT INTO posts(post_id,platform_id,native_post_id,availability,
                                 first_seen_at,last_seen_at)
               VALUES(501,(SELECT platform_id FROM platforms WHERE platform_key='gelbooru'),
                      '123','available',?,?)""",
            (NOW, NOW),
        )
        c.execute(
            """INSERT INTO media_occurrences(media_occurrence_id,post_id,source_key,
                   media_index,media_type,role,remote_url,preview_url,mime_type,
                   availability,observed_at)
               VALUES(601,501,'primary',0,'image','primary',?,?,'image/jpeg','available',?)""",
            (URL, URL.replace("test.jpg", "preview.jpg"), NOW),
        )
        c.commit()
        yield db


@pytest.fixture
def sankaku_database(database, monkeypatch):
    c = database.connection
    c.execute("INSERT OR IGNORE INTO platforms(platform_key,display_name) VALUES('sankaku','S')")
    c.execute(
        "UPDATE posts SET platform_id=(SELECT platform_id FROM platforms "
        "WHERE platform_key='sankaku'),native_post_id=?,canonical_url=?",
        (SANKAKU_POST, "https://sankaku.app/posts/" + SANKAKU_POST),
    )
    c.execute(
        "UPDATE media_occurrences SET remote_url=?,declared_md5=?",
        ("https://v.sankakucomplex.com/data/old.jpg?expires=1&token=old", "a" * 32),
    )
    c.commit()
    monkeypatch.setenv("SANKAKU_LOGIN", "sentinel-login")
    monkeypatch.setenv("SANKAKU_PASSWORD", "sentinel-password")
    return database


def sankaku_api_response(request, *, md5="a" * 32, post_id=SANKAKU_POST, url=SANKAKU_FRESH):
    if request.url.path == "/auth/token":
        assert request.url.host == "sankakuapi.com"
        return httpx.Response(200, json={"success": True, "access_token": "sentinel-token"})
    assert request.headers["Authorization"] == "Bearer sentinel-token"
    return httpx.Response(
        200,
        json=[
            {
                "id": post_id,
                "file_url": url,
                "md5": md5,
                "file_type": "image/jpeg",
                "tags": [],
            }
        ],
    )


@pytest.mark.parametrize("old_denied", [False, True])
def test_sankaku_expiry_and_fresh403_renew_once(sankaku_database, old_denied, tmp_path):
    c = sankaku_database.connection
    if old_denied:
        c.execute(
            "UPDATE media_occurrences SET remote_url='https://v.sankakucomplex.com/data/old.jpg?expires=4102444800'"
        )
        c.commit()
    calls = []

    def upstream(request):
        calls.append(request)
        if request.url.host == "sankakuapi.com":
            return sankaku_api_response(request)
        assert request.url.host == "v.sankakucomplex.com"
        assert "Chrome/108" in request.headers["User-Agent"]
        assert "Authorization" not in request.headers
        assert "cookie" not in request.headers
        if request.url.path.endswith("old.jpg"):
            assert old_denied
            return httpx.Response(403)
        assert str(request.url) == SANKAKU_FRESH
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"jpeg")

    resolver = SankakuDisplayResolver()
    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        for _ in range(2):
            result = fetch_remote_media(c, 601, "primary", client=client, sankaku_resolver=resolver)
            assert result.body == b"jpeg"
    assert sum(r.url.path == "/auth/token" for r in calls) == 1
    assert sum(r.url.path.endswith("old.jpg") for r in calls) == int(old_denied)
    assert c.execute("SELECT remote_url FROM media_occurrences").fetchone()[0].find("old.jpg") >= 0
    assert c.execute("SELECT count(*) FROM raw_observations").fetchone()[0] == 0
    view = LabelingState(c, tmp_path)._resolve_post_media(501)
    assert view["src"] == "/remote-media/601/primary"
    assert view["source_url"] == "https://sankaku.app/posts/" + SANKAKU_POST


def test_sankaku_denied_after_renewal_stops(sankaku_database):
    calls = []

    def upstream(request):
        calls.append(request)
        if request.url.host == "sankakuapi.com":
            return sankaku_api_response(request)
        return httpx.Response(403)

    with (
        httpx.Client(transport=httpx.MockTransport(upstream)) as client,
        pytest.raises(RemoteMediaError, match="Sankaku denied media after renewing"),
    ):
        fetch_remote_media(sankaku_database.connection, 601, "primary", client=client)
    assert len(calls) == 3


@pytest.mark.parametrize("bad_kind", ["hash", "post", "destination"])
def test_sankaku_refresh_cannot_substitute_identity_or_host(sankaku_database, bad_kind):
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.url.host == "sankakuapi.com"
        kwargs = {}
        if bad_kind == "hash":
            kwargs["md5"] = "b" * 32
        if bad_kind == "post":
            kwargs["post_id"] = "wvaemE6YDaz"
        if bad_kind == "destination":
            kwargs["url"] = "https://evil.example/a.jpg"
        return sankaku_api_response(request, **kwargs)

    with (
        httpx.Client(transport=httpx.MockTransport(upstream)) as client,
        pytest.raises(RemoteMediaError),
    ):
        fetch_remote_media(sankaku_database.connection, 601, "primary", client=client)
    assert len(calls) == 2


def test_sankaku_missing_credentials_is_safe(sankaku_database, monkeypatch):
    monkeypatch.delenv("SANKAKU_PASSWORD")

    def upstream(request):
        pytest.fail("Request made without required credentials")

    with (
        httpx.Client(transport=httpx.MockTransport(upstream)) as client,
        pytest.raises(RemoteMediaError) as error,
    ):
        fetch_remote_media(sankaku_database.connection, 601, "primary", client=client)
    assert str(error.value) == "Sankaku media renewal failed; check provider access"


def test_remote_image_uses_provider_headers_without_acquiring_assets(database):
    def upstream(request):
        assert str(request.url) == URL
        assert request.headers["Referer"] == "https://gelbooru.com/"
        assert "cookie" not in request.headers
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"jpeg")

    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        result = fetch_remote_media(database.connection, 601, "primary", client=client)
    assert result.body == b"jpeg"
    assert result.content_type == "image/jpeg"
    assert database.connection.execute("SELECT count(*) FROM assets").fetchone()[0] == 0
    assert database.connection.execute("SELECT count(*) FROM pair_labels").fetchone()[0] == 0


def test_remote_urls_in_page_use_local_endpoint(database, tmp_path):
    state = LabelingState(database.connection, tmp_path)
    view = state._resolve_post_media(501)
    assert view["src"] == "/remote-media/601/primary"
    assert view["source_url"] == URL
    assert view["mime"] == "image/jpeg"
    database.connection.execute("UPDATE media_occurrences SET remote_url=NULL")
    assert state._resolve_post_media(501)["src"] == "/remote-media/601/preview"


@pytest.mark.parametrize("destination", ["http://127.0.0.1/a", "https://evil.example/a"])
def test_remote_endpoint_rejects_foreign_destinations(database, destination):
    database.connection.execute("UPDATE media_occurrences SET remote_url=?", (destination,))

    def upstream(request):
        pytest.fail("Disallowed destination reached the transport")

    with (
        httpx.Client(transport=httpx.MockTransport(upstream)) as client,
        pytest.raises(RemoteMediaError, match="Provider media request failed"),
    ):
        fetch_remote_media(database.connection, 601, "primary", client=client)


def test_remote_redirect_is_validated_before_following(database):
    requests = []

    def upstream(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.example/private-token"})

    with (
        httpx.Client(transport=httpx.MockTransport(upstream)) as client,
        pytest.raises(RemoteMediaError) as error,
    ):
        fetch_remote_media(database.connection, 601, "primary", client=client)
    assert len(requests) == 1
    assert "private-token" not in str(error.value)


@pytest.mark.parametrize("mime", ["text/html", "image/svg+xml"])
def test_remote_active_content_is_not_served(database, mime):
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, headers={"Content-Type": mime}, content=b"active"
                )
            )
        ) as client,
        pytest.raises(RemoteMediaError),
    ):
        fetch_remote_media(database.connection, 601, "primary", client=client)


def test_remote_video_range_is_forwarded(database):
    def upstream(request):
        assert request.headers["Range"] == "bytes=2-5"
        return httpx.Response(
            206,
            headers={"Content-Type": "video/webm", "Content-Range": "bytes 2-5/10"},
            content=b"2345",
        )

    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        result = fetch_remote_media(
            database.connection, 601, "primary", range_header="bytes=2-5", client=client
        )
    assert result.status == 206
    assert result.content_range == "bytes 2-5/10"
    assert result.body == b"2345"


def test_wrong_remote_video_range_is_rejected(database):
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    206,
                    headers={"Content-Type": "video/webm", "Content-Range": "bytes 0-3/10"},
                    content=b"0123",
                )
            )
        ) as client,
        pytest.raises(RemoteMediaError, match="Unexpected remote media range"),
    ):
        fetch_remote_media(
            database.connection, 601, "primary", range_header="bytes=2-5", client=client
        )


@pytest.mark.parametrize(
    ("requested", "returned", "body"),
    [
        ("bytes=-5", "bytes 5-9/10", b"56789"),
        ("bytes=0-", "bytes 0-3/10", b"0123"),
        ("bytes=2-8", "bytes 2-5/10", b"2345"),
    ],
)
def test_remote_cdn_may_return_a_subset_of_requested_range(database, requested, returned, body):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                206,
                headers={"Content-Type": "video/webm", "Content-Range": returned},
                content=body,
            )
        )
    ) as client:
        result = fetch_remote_media(
            database.connection, 601, "primary", range_header=requested, client=client
        )
    assert result.body == body
    assert result.content_range == returned


def test_same_host_redirect_preserves_provider_headers(database):
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.headers["Referer"] == "https://gelbooru.com/"
        if len(calls) == 1:
            return httpx.Response(302, headers={"Location": "/images/final.jpg"})
        assert request.url.path == "/images/final.jpg"
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"jpeg")

    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        assert (
            fetch_remote_media(database.connection, 601, "primary", client=client).body == b"jpeg"
        )
    assert len(calls) == 2


def test_octet_stream_video_preview_preserves_video_type(database, tmp_path):
    c = database.connection
    c.execute(
        "UPDATE media_occurrences SET remote_url=NULL,preview_url='https://img4.gelbooru.com/a.webm',mime_type='video/webm'"
    )
    assert LabelingState(c, tmp_path)._resolve_post_media(501)["mime"] == "video/webm"
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Type": "application/octet-stream"},
                content=b"video",
            )
        )
    ) as client:
        assert fetch_remote_media(c, 601, "preview", client=client).content_type == "video/webm"


def test_aibooru_observed_cdn_is_admitted_but_unrelated_host_is_not(database):
    c = database.connection
    c.execute("INSERT OR IGNORE INTO platforms(platform_key,display_name) VALUES('aibooru','A')")
    c.execute(
        "UPDATE posts SET platform_id=(SELECT platform_id FROM platforms "
        "WHERE platform_key='aibooru')"
    )
    c.execute(
        "UPDATE media_occurrences SET remote_url='https://cdn.aibooru.download/original/a.jpg'"
    )
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.url.host == "cdn.aibooru.download"
        assert request.headers["Referer"] == "https://aibooru.online/"
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"jpeg")

    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        assert fetch_remote_media(c, 601, "primary", client=client).body == b"jpeg"
        c.execute(
            "UPDATE media_occurrences SET remote_url='https://cdn.aibooru.download.evil.example/a.jpg'"
        )
        with pytest.raises(RemoteMediaError):
            fetch_remote_media(c, 601, "primary", client=client)
    assert len(calls) == 1


def test_remote_transport_error_does_not_expose_url(database):
    def upstream(request):
        raise httpx.ReadTimeout("private-token " + str(request.url), request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(upstream)) as client,
        pytest.raises(RemoteMediaError) as error,
    ):
        fetch_remote_media(database.connection, 601, "primary", client=client)
    assert str(error.value) == "Provider media request failed"


def test_remote_size_limit_applies_without_content_length(database, monkeypatch):
    monkeypatch.setattr(remote, "MAX_REMOTE_BYTES", 3)
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, headers={"Content-Type": "image/jpeg"}, stream=httpx.ByteStream(b"1234")
                )
            )
        ) as client,
        pytest.raises(RemoteMediaError, match="size limit"),
    ):
        fetch_remote_media(database.connection, 601, "primary", client=client)


def test_production_remote_endpoint(database, tmp_path, monkeypatch):
    calls = []
    fail = False
    real_client = httpx.Client

    def upstream(request):
        calls.append(request)
        if fail:
            raise RuntimeError("private-token in an unexpected upstream exception")
        assert request.headers["Referer"] == "https://gelbooru.com/"
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"jpeg")

    monkeypatch.setattr(
        httpx, "Client", lambda: real_client(transport=httpx.MockTransport(upstream))
    )
    ready = threading.Event()
    servers = []

    def serve():
        server, db, _ = create_server(database.path, tmp_path, port=0)
        servers.append(server)
        ready.set()
        try:
            server.serve_forever()
        finally:
            server.server_close()
            db.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(10)
    base = f"http://127.0.0.1:{servers[0].server_port}"
    try:
        with urlopen(base + "/remote-media/601/primary", timeout=10) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "image/jpeg"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["Accept-Ranges"] == "bytes"
            assert response.headers["Cache-Control"] == "private, max-age=60"
            assert response.read() == b"jpeg"
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/remote-media/601/primary?url=https://evil.example", timeout=10)
        assert error.value.code == 404
        assert len(calls) == 1
        with pytest.raises(HTTPError) as invalid_range:
            urlopen(
                Request(base + "/remote-media/601/primary", headers={"Range": "bytes=8-2"}),
                timeout=10,
            )
        assert invalid_range.value.code == 416
        assert len(calls) == 1
        fail = True
        with pytest.raises(HTTPError) as unexpected:
            urlopen(base + "/remote-media/601/primary", timeout=10)
        assert unexpected.value.code == 502
        assert unexpected.value.read() == b"Provider media request failed"
    finally:
        servers[0].shutdown()
        thread.join(10)
