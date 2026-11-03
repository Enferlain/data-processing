"""Explicit bounded metadata synchronization and enrichment: metadata."""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from media_catalog.adapter_factory import adapter_construction
from media_catalog.adapters import AdapterOperation
from media_catalog.adapters.danbooru import AIBOORU, DANBOORU
from media_catalog.adapters.e621 import E621_INSTANCES
from media_catalog.adapters.gelbooru import GELBOORU, GELBOORU_INSTANCES, GelbooruHtmlAdapter
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.cli_commands.support import (
    E621_CREDENTIAL_GUIDANCE,
    GELBOORU_DAPI_CREDENTIAL_GUIDANCE,
    GELBOORU_HTML_GUIDANCE,
    SANKAKU_CREDENTIAL_GUIDANCE,
    add_json,
    add_sync_limits,
    utc_now,
)
from media_catalog.database import CatalogDatabase
from media_catalog.output import public_path
from media_catalog.remote_queries import get_remote_run, list_remote_runs
from media_catalog.remote_sync import MetadataSyncService, SyncLimits
from media_catalog.remote_sync.enrichment import fetch_commentary, fetch_notes
from media_catalog.remote_sync.pools import fetch_pool

OPERATIONS = {
    "pixiv-profile": False,
    "pixiv-artwork": False,
    "pixiv-account-artworks": True,
    "danbooru-post": False,
    "danbooru-artist": False,
    "danbooru-pool": False,
    "danbooru-commentary": False,
    "danbooru-list": True,
    "aibooru-post": False,
    "aibooru-artist": False,
    "aibooru-pool": False,
    "aibooru-commentary": False,
    "aibooru-list": True,
    "e621-post": False,
    "e621-artist": False,
    "e621-tag": False,
    "e621-alias": False,
    "e621-list": True,
    "gelbooru-dapi-post": False,
    "gelbooru-dapi-tag": False,
    "gelbooru-dapi-notes": False,
    "gelbooru-dapi-list": True,
    "e621-notes": False,
    "gelbooru-html-post": False,
    "sankaku-post": False,
    "sankaku-list": True,
    "pawchive-profile": False,
    "pawchive-post": False,
    "pawchive-list": True,
}


COMMANDS = ("metadata",)


def register(commands: argparse._SubParsersAction) -> None:
    metadata = commands.add_parser(
        "metadata",
        description=(f"Explicit bounded metadata synchronization. {E621_CREDENTIAL_GUIDANCE}"),
    )
    metadata_commands = metadata.add_subparsers(dest="metadata_command", required=True)

    def _metadata_description(name: str) -> str | None:
        if name.startswith("e621-"):
            return E621_CREDENTIAL_GUIDANCE
        if name.startswith("gelbooru-dapi-"):
            return GELBOORU_DAPI_CREDENTIAL_GUIDANCE
        if name == "gelbooru-html-post":
            return GELBOORU_HTML_GUIDANCE
        if name.startswith("sankaku-"):
            return SANKAKU_CREDENTIAL_GUIDANCE
        return None

    for name, listing in OPERATIONS.items():
        command = metadata_commands.add_parser(name, description=_metadata_description(name))
        command.add_argument("catalog", type=Path)
        command.add_argument("target")
        add_sync_limits(command, listing=listing)
        if name.startswith("gelbooru-dapi-"):
            # Instance selection is explicit on every gelbooru-engine DAPI
            # surface; the HTML transport stays canonical-gelbooru only.
            command.add_argument(
                "--instance", choices=tuple(GELBOORU_INSTANCES), default="gelbooru"
            )
        if name.startswith("e621-"):
            # Instance selection is explicit on every e621-engine surface.
            command.add_argument("--instance", choices=tuple(E621_INSTANCES), default="e621")
    remote_runs = metadata_commands.add_parser("runs")
    remote_runs.add_argument("catalog", type=Path)
    remote_runs.add_argument("--limit", type=int, default=100)
    add_json(remote_runs)
    remote_show = metadata_commands.add_parser("run-show")
    remote_show.add_argument("catalog", type=Path)
    remote_show.add_argument("run_id", type=int)
    add_json(remote_show)


def _factory_sync(
    arguments: argparse.Namespace,
    catalog_label: str,
    limits: SyncLimits,
    operation: AdapterOperation,
    platform: str,
) -> dict[str, object]:
    factory, interval = adapter_construction(platform)
    with httpx.Client() as client, CatalogDatabase(arguments.catalog) as database:
        adapter = factory(client)
        result = MetadataSyncService(
            database,
            adapter,
            minimum_interval_seconds=interval,
        ).synchronize(
            operation,
            arguments.target,
            limits=limits,
            resume_from_run_id=arguments.resume_from,
        )
    return {"catalog": catalog_label, **result.as_dict()}


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    catalog_label = public_path(arguments.catalog)
    if arguments.metadata_command == "runs":
        results = list_remote_runs(arguments.catalog, limit=arguments.limit)
        return {"catalog": catalog_label, "count": len(results), "results": results}
    if arguments.metadata_command == "run-show":
        result = get_remote_run(arguments.catalog, arguments.run_id)
        if result is None:
            raise ValueError("remote run not found")
        return {"catalog": catalog_label, **result}
    limits = SyncLimits(
        arguments.max_requests,
        arguments.max_pages,
        arguments.max_records,
        arguments.max_seconds,
    )
    command = arguments.metadata_command
    if command.startswith("pixiv-"):
        operation = {
            "pixiv-profile": AdapterOperation.FETCH_ACCOUNT,
            "pixiv-artwork": AdapterOperation.FETCH_POST,
            "pixiv-account-artworks": AdapterOperation.LIST_ACCOUNT_POSTS,
        }[command]
        with (
            CatalogDatabase(arguments.catalog) as database,
            PixivAdapter(require_auth=True) as adapter,
        ):
            result = MetadataSyncService(database, adapter).synchronize(
                operation,
                arguments.target,
                limits=limits,
                resume_from_run_id=arguments.resume_from,
            )
        return {"catalog": catalog_label, **result.as_dict()}
    if command == "gelbooru-dapi-notes" or command == "e621-notes":
        if arguments.resume_from is not None:
            raise ValueError("--resume-from is not supported for enrichment fetches")
        with httpx.Client() as client, CatalogDatabase(arguments.catalog) as database:
            notes_factory, _interval = adapter_construction(arguments.instance)
            adapter = notes_factory(client)
            return {
                "catalog": catalog_label,
                **fetch_notes(
                    database,
                    adapter,
                    arguments.target,
                    clock=utc_now,
                    time_budget_seconds=int(limits.elapsed_seconds),
                ),
            }
    if command.startswith("gelbooru-"):
        # The transport is part of the command name; there is never a
        # silent fallback between the credentialed DAPI and anonymous
        # HTML transports.
        resume_from = arguments.resume_from
        if resume_from is not None and command != "gelbooru-dapi-list":
            raise ValueError("--resume-from is only supported for gelbooru-dapi-list")
        if command == "gelbooru-html-post":
            with httpx.Client() as client, CatalogDatabase(arguments.catalog) as database:
                adapter = GelbooruHtmlAdapter(GELBOORU, client=client)
                result = MetadataSyncService(
                    database,
                    adapter,
                    minimum_interval_seconds=GELBOORU.minimum_interval_seconds,
                ).synchronize(
                    AdapterOperation.FETCH_POST,
                    arguments.target,
                    limits=limits,
                    resume_from_run_id=resume_from,
                )
            return {"catalog": catalog_label, **result.as_dict()}
        return _factory_sync(
            arguments,
            catalog_label,
            limits,
            {
                "gelbooru-dapi-post": AdapterOperation.FETCH_POST,
                "gelbooru-dapi-tag": AdapterOperation.FETCH_TAG,
                "gelbooru-dapi-list": AdapterOperation.LIST_ACCOUNT_POSTS,
            }[command],
            arguments.instance,
        )
    if command.startswith("sankaku-"):
        return _factory_sync(
            arguments,
            catalog_label,
            limits,
            {
                "sankaku-post": AdapterOperation.FETCH_POST,
                "sankaku-list": AdapterOperation.LIST_ACCOUNT_POSTS,
            }[command],
            "sankaku",
        )
    if command.startswith("pawchive-"):
        return _factory_sync(
            arguments,
            catalog_label,
            limits,
            {
                "pawchive-profile": AdapterOperation.FETCH_ACCOUNT,
                "pawchive-post": AdapterOperation.FETCH_POST,
                "pawchive-list": AdapterOperation.LIST_ACCOUNT_POSTS,
            }[command],
            "pawchive",
        )
    if command.startswith("e621-"):
        return _factory_sync(
            arguments,
            catalog_label,
            limits,
            {
                "e621-post": AdapterOperation.FETCH_POST,
                "e621-artist": AdapterOperation.FETCH_ATTRIBUTION,
                "e621-tag": AdapterOperation.FETCH_TAG,
                "e621-alias": AdapterOperation.FETCH_TAG_ALIAS,
                "e621-list": AdapterOperation.LIST_ACCOUNT_POSTS,
            }[command],
            arguments.instance,
        )
    instance = AIBOORU if command.startswith("aibooru-") else DANBOORU
    if command.endswith("-commentary"):
        # Opt-in enrichment: never part of default post sync.
        if arguments.resume_from is not None:
            raise ValueError("--resume-from is not supported for enrichment fetches")
        danbooru_factory, _ = adapter_construction(instance.platform_key)
        with httpx.Client() as client, CatalogDatabase(arguments.catalog) as database:
            adapter = danbooru_factory(client)
            return {
                "catalog": catalog_label,
                **fetch_commentary(
                    database,
                    adapter,
                    arguments.target,
                    clock=utc_now,
                    time_budget_seconds=int(limits.elapsed_seconds),
                ),
            }
    if command.endswith("-pool"):
        # One request, one pool: the endpoint does not paginate, so only
        # the time budget is operator-tunable; there is nothing to resume.
        if arguments.resume_from is not None:
            raise ValueError("--resume-from is not supported for pool fetches")
        danbooru_factory, _ = adapter_construction(instance.platform_key)
        with httpx.Client() as client, CatalogDatabase(arguments.catalog) as database:
            adapter = danbooru_factory(client)
            return {
                "catalog": catalog_label,
                **fetch_pool(
                    database,
                    adapter,
                    int(arguments.target),
                    clock=utc_now,
                    time_budget_seconds=int(limits.elapsed_seconds),
                ),
            }
    return _factory_sync(
        arguments,
        catalog_label,
        limits,
        (
            AdapterOperation.FETCH_POST
            if command.endswith("-post")
            else (
                AdapterOperation.FETCH_ATTRIBUTION
                if command.endswith("-artist")
                else AdapterOperation.LIST_ACCOUNT_POSTS
            )
        ),
        instance.platform_key,
    )
