"""Link-driven ingest and discovery sessions: fetch, discover."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import httpx

from media_catalog.adapter_factory import adapter_construction
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.cli_commands.support import add_json, add_sync_limits
from media_catalog.database import CatalogDatabase
from media_catalog.discovery import DiscoveryOrchestrator
from media_catalog.link_resolution import resolve_link
from media_catalog.output import public_path
from media_catalog.remote_sync import MetadataSyncService, SyncLimits


def _fetch_adapter_for(platform: str) -> tuple[Any, float]:
    return adapter_construction(platform)


COMMANDS = ("fetch", "discover")


def register(commands: argparse._SubParsersAction) -> None:
    fetch = commands.add_parser(
        "fetch",
        description=(
            "Resolve a supported-site URL and sync its metadata"
            " (gelbooru-family links need DAPI credentials in the environment)"
        ),
    )
    fetch.add_argument("catalog", type=Path)
    fetch.add_argument("url", help="https post URL from any supported platform")
    add_sync_limits(fetch, listing=False)
    fetch.add_argument("--resolve-only", action="store_true")
    discover_cmd = commands.add_parser(
        "discover",
        description="One input initiates a bounded discovery session (offline plan by default)",
    )
    discover_cmd.add_argument("catalog", type=Path)
    input_group = discover_cmd.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--url", help="post URL from any supported platform")
    input_group.add_argument("--post", type=int, help="existing catalog post id")
    input_group.add_argument("--account", type=int, help="existing catalog account id")
    input_group.add_argument(
        "--session", type=int, help="re-report a prior session instead of starting one"
    )
    discover_cmd.add_argument("--file", type=Path, help="local file held for the URL seed")
    discover_cmd.add_argument("--media-root", type=Path)
    discover_cmd.add_argument("--declared-md5")
    discover_cmd.add_argument("--note")
    discover_cmd.add_argument("--live", action="store_true")
    discover_cmd.add_argument("--max-requests", type=int, default=12)
    discover_cmd.add_argument("--max-seconds", type=int, default=120)
    discover_cmd.add_argument("--search-term", help="artist search term for account-seed discovery")
    add_json(discover_cmd)


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.command == "fetch":
        return _execute_fetch(arguments)
    return _execute_discover(arguments)


def _execute_fetch(arguments: argparse.Namespace) -> dict[str, object]:
    resolved = resolve_link(arguments.url)
    catalog_label = public_path(arguments.catalog)
    if arguments.resolve_only:
        return {
            "catalog": catalog_label,
            "url": arguments.url,
            "platform": resolved.platform,
            "operation": resolved.operation.value,
            "target": resolved.target,
            "canonical_url": resolved.canonical_url,
            "status": "resolved",
        }
    limits = SyncLimits(
        arguments.max_requests,
        arguments.max_pages,
        arguments.max_records,
        arguments.max_seconds,
    )
    adapter, minimum_interval = _fetch_adapter_for(resolved.platform)
    with httpx.Client() as client:
        bound = adapter(client)
        if isinstance(bound, PixivAdapter):
            with bound as pixiv_adapter, CatalogDatabase(arguments.catalog) as database:
                result = MetadataSyncService(
                    database,
                    pixiv_adapter,
                    minimum_interval_seconds=minimum_interval,
                ).synchronize(
                    resolved.operation,
                    resolved.target,
                    limits=limits,
                    resume_from_run_id=arguments.resume_from,
                )
        else:
            with CatalogDatabase(arguments.catalog) as database:
                result = MetadataSyncService(
                    database,
                    bound,
                    minimum_interval_seconds=minimum_interval,
                ).synchronize(
                    resolved.operation,
                    resolved.target,
                    limits=limits,
                    resume_from_run_id=arguments.resume_from,
                )
    return {
        "catalog": catalog_label,
        "url": arguments.url,
        "platform": resolved.platform,
        "target": resolved.target,
        "canonical_url": resolved.canonical_url,
        **result.as_dict(),
    }


def _execute_discover(arguments: argparse.Namespace) -> dict[str, object]:
    if not 1 <= arguments.max_requests <= 100:
        raise ValueError("--max-requests must be between 1 and 100")
    if not 1 <= arguments.max_seconds <= 3600:
        raise ValueError("--max-seconds must be between 1 and 3600")
    catalog_label = public_path(arguments.catalog)
    with CatalogDatabase(arguments.catalog) as database:
        service = DiscoveryOrchestrator(database)
        if arguments.session is not None:
            result = service.report(arguments.session)
        else:
            result = service.start(
                url=arguments.url,
                file=arguments.file,
                media_root=arguments.media_root,
                declared_md5=arguments.declared_md5,
                note=arguments.note,
                post_id=arguments.post,
                account_id=arguments.account,
                live=arguments.live,
                request_budget=arguments.max_requests,
                time_budget_seconds=arguments.max_seconds,
                search_term=arguments.search_term,
            )
    return {"catalog": catalog_label, **result}
