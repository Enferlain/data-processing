"""Link-driven ingest: URL resolution and the fetch command surface.

The resolver is pure parsing over URL grammars every normalizer already
produces as canonical_url; no network and no new wire contracts.  The fetch
command composes resolution with the existing metadata sync path.
"""

from __future__ import annotations

import json

import pytest

from media_catalog.adapters.contracts import AdapterOperation
from media_catalog.link_resolution import (
    RESOLVED_PLATFORMS,
    resolve_link,
)

# One committed-fixture post per platform: each URL is the canonical form of
# a post the repo has already captured, so the grammars stay honest.
CASES = {
    "danbooru": ("https://danbooru.donmai.us/posts/3001", "3001"),
    "aibooru": ("https://aibooru.online/posts/3001", "3001"),
    "e621": ("https://e621.net/posts/5001", "5001"),
    "e926": ("https://e926.net/posts/6823045", "6823045"),
    "gelbooru": (
        "https://gelbooru.com/index.php?page=post&s=view&id=12370900",
        "12370900",
    ),
    "safebooru": (
        "https://safebooru.org/index.php?page=post&s=view&id=7272295",
        "7272295",
    ),
    "rule34": (
        "https://rule34.xxx/index.php?page=post&s=view&id=19210742",
        "19210742",
    ),
    "pixiv": ("https://www.pixiv.net/artworks/2997", "2997"),
    "sankaku": ("https://sankaku.app/posts/wvaemE6YDaz", "wvaemE6YDaz"),
    "pawchive": (
        "https://pawchive.pw/patreon/user/75232195/post/70439020",
        "patreon:75232195:70439020",
    ),
}


@pytest.mark.parametrize("platform", sorted(CASES))
def test_every_supported_platform_resolves(platform: str) -> None:
    url, target = CASES[platform]
    resolved = resolve_link(url)
    assert resolved.platform == platform
    assert resolved.operation is AdapterOperation.FETCH_POST
    assert resolved.target == target
    assert resolved.canonical_url.startswith("https://")


def test_resolution_covers_the_registered_platforms() -> None:
    assert {resolved.platform for resolved in (resolve_link(url) for url, _ in CASES.values())} == (
        RESOLVED_PLATFORMS
    )


@pytest.mark.parametrize(
    ("url", "platform", "target"),
    [
        ("https://danbooru.donmai.us/posts/5001.json", "danbooru", "5001"),
        ("https://www.pixiv.net/en/artworks/2997", "pixiv", "2997"),
        (
            "https://www.rule34.xxx/index.php?page=post&s=view&id=19210742",
            "rule34",
            "19210742",
        ),
        (
            "https://api.rule34.xxx/index.php?page=post&s=view&id=19210742",
            "rule34",
            "19210742",
        ),
        (
            "https://chan.sankakucomplex.com/posts/wvaemE6YDaz",
            "sankaku",
            "wvaemE6YDaz",
        ),
        (
            "https://chan.sankakucomplex.com/en/posts/AZrKYlgK2M5",
            "sankaku",
            "AZrKYlgK2M5",
        ),
        (
            "https://danbooru.donmai.us/en/posts/12495119",
            "danbooru",
            "12495119",
        ),
        (
            "https://www.pawchive.pw/patreon/user/75232195/post/70439020",
            "pawchive",
            "patreon:75232195:70439020",
        ),
        ("https://www.aibooru.online/posts/3001", "aibooru", "3001"),
        (
            "https://www.pixiv.net/member_illust.php?mode=medium&illust_id=2997",
            "pixiv",
            "2997",
        ),
        (" https://e621.net/posts/5001 ", "e621", "5001"),
    ],
)
def test_pasted_url_variants_resolve(url: str, platform: str, target: str) -> None:
    resolved = resolve_link(url)
    assert resolved.platform == platform
    assert resolved.target == target


def test_fetch_resolve_only_never_touches_the_catalog(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    from media_catalog.cli import main

    main(
        [
            "fetch",
            str(tmp_path / "unused.sqlite3"),
            "https://e926.net/posts/6823045",
            "--resolve-only",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "resolved"
    assert payload["platform"] == "e926"
    assert payload["target"] == "6823045"


def test_fetch_routes_the_resolved_platform(
    tmp_path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import media_catalog.cli_commands.discovery as discovery_module
    from media_catalog.cli import main
    from media_catalog.database import CatalogDatabase
    from media_catalog.remote_sync import SyncResult

    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass
    sync_calls: list[tuple[AdapterOperation, str]] = []

    class FakeService:
        def __init__(self, _database: CatalogDatabase, _adapter: object, **kwargs: object) -> None:
            pass

        def synchronize(
            self,
            operation: AdapterOperation,
            target: str,
            *,
            limits: object,
            resume_from_run_id: int | None,
        ) -> SyncResult:
            sync_calls.append((operation, target))
            return SyncResult(
                remote_run_id=99,
                platform="e926",
                operation=operation.value,
                target=target,
                status="complete",
                outcome="success",
                request_count=1,
                page_count=1,
                record_count=1,
                resumed_from_run_id=resume_from_run_id,
            )

    monkeypatch.setattr(discovery_module, "MetadataSyncService", FakeService)

    class _RouteStub:
        pass

    # Route through the real _fetch_adapter_for to prove platform dispatch.
    original = discovery_module._fetch_adapter_for
    captured: list[str] = []

    def spy(platform: str):
        captured.append(platform)
        return original(platform)

    monkeypatch.setattr(discovery_module, "_fetch_adapter_for", spy)
    # The real E621 adapter is constructed but FakeService replaces the sync,
    # so the E621 wire is never contacted.
    monkeypatch.delenv("E621_USERNAME", raising=False)
    monkeypatch.delenv("E621_API_KEY", raising=False)

    main(["fetch", str(catalog), "https://e926.net/posts/6823045", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert captured == ["e926"]
    assert sync_calls == [(AdapterOperation.FETCH_POST, "6823045")]
    assert payload["status"] == "complete"
    assert payload["remote_run_id"] == 99


def test_fetch_failed_sync_exits_nonzero(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed fetch must fail the process, like the metadata family."""
    from media_catalog.cli import main
    from media_catalog.database import CatalogDatabase
    from media_catalog.remote_sync import SyncResult

    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass

    class FailingService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def synchronize(self, *_args: object, **_kwargs: object) -> SyncResult:
            return SyncResult(
                remote_run_id=7,
                platform="e621",
                operation="fetch_post",
                target="1",
                status="failed",
                outcome="malformed_response",
                request_count=1,
                page_count=0,
                record_count=0,
                resumed_from_run_id=None,
            )

    import media_catalog.cli_commands.discovery as discovery_family

    monkeypatch.setattr(discovery_family, "MetadataSyncService", FailingService)
    monkeypatch.delenv("E621_USERNAME", raising=False)
    monkeypatch.delenv("E621_API_KEY", raising=False)
    with pytest.raises(SystemExit) as raised:
        main(["fetch", str(catalog), "https://e621.net/posts/1", "--json"])
    assert raised.value.code == 2
    # The failure is still rendered before the nonzero exit.
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_legacy_post_show_paths_resolve() -> None:
    """Danbooru-family and e621-family legacy /post/show/<id> pages (used in
    the operator's test list) resolve to the same identity as /posts/<id>."""
    from media_catalog.link_resolution import resolve_link

    for url, platform, target in (
        ("https://danbooru.donmai.us/post/show/9714844", "danbooru", "9714844"),
        ("https://e621.net/post/show/5433323", "e621", "5433323"),
    ):
        resolved = resolve_link(url)
        assert (resolved.platform, resolved.target) == (platform, target)
        assert resolved.canonical_url.endswith(f"/posts/{target}")
