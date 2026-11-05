"""Catalog data maintenance: reprocess (offline replay), seed creation."""

from __future__ import annotations

import argparse
from pathlib import Path

from media_catalog.cli_commands.support import (
    add_json,
    offline_replay_adapter,
    utc_now,
)
from media_catalog.database import CatalogDatabase
from media_catalog.output import public_path
from media_catalog.remote_sync import execute_reprocess, plan_reprocess
from media_catalog.seeding import SeedMaterializationService
from media_catalog.tombstone import tombstone_lookup_run, tombstone_posts

_REPROCESS_PROVIDERS = (
    "danbooru",
    "aibooru",
    "gelbooru",
    "safebooru",
    "rule34",
    "e621",
    "e926",
    "pawchive",
)


COMMANDS = ("reprocess", "seed", "tombstone")


def register(commands: argparse._SubParsersAction) -> None:
    reprocess = commands.add_parser("reprocess")
    reprocess_commands = reprocess.add_subparsers(dest="reprocess_command", required=True)
    reprocess_plan = reprocess_commands.add_parser("plan")
    reprocess_plan.add_argument("catalog", type=Path)
    reprocess_plan.add_argument("--provider", choices=_REPROCESS_PROVIDERS, required=True)
    reprocess_plan.add_argument("--limit", type=int, default=100)
    add_json(reprocess_plan)
    reprocess_run = reprocess_commands.add_parser("run")
    reprocess_run.add_argument("catalog", type=Path)
    reprocess_run.add_argument("--provider", choices=_REPROCESS_PROVIDERS, required=True)
    reprocess_run.add_argument("--raw-id", action="append", type=int, required=True)
    add_json(reprocess_run)

    seed = commands.add_parser("seed")
    seed_commands = seed.add_subparsers(dest="seed_command", required=True)
    seed_create = seed_commands.add_parser("create")
    seed_create.add_argument("catalog", type=Path)
    seed_create.add_argument(
        "--url", metavar="URL", action="append", required=True, help="where the item was found"
    )
    seed_create.add_argument("--note", help="private operator note retained with the bundle")
    seed_create.add_argument("--declared-md5", help="declared 32-character hex MD5")
    seed_create.add_argument(
        "--file", type=Path, help="local file the operator holds (innate metadata is preferred)"
    )
    seed_create.add_argument(
        "--media-root",
        type=Path,
        help="existing managed media root for adopting --file into verified storage",
    )
    add_json(seed_create)

    tombstone = commands.add_parser(
        "tombstone",
        description="Mark bad data as errored without deleting evidence",
    )
    tombstone.add_argument("catalog", type=Path)
    tombstone_target = tombstone.add_mutually_exclusive_group(required=True)
    tombstone_target.add_argument("--post", type=int, action="append")
    tombstone_target.add_argument("--lookup-run", type=int)
    tombstone.add_argument("--reason", required=True, help="recorded with the tombstone")
    add_json(tombstone)


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    catalog_label = public_path(arguments.catalog)
    if arguments.command == "reprocess":
        if arguments.reprocess_command == "plan":
            adapter = offline_replay_adapter(arguments.provider)
            with CatalogDatabase(arguments.catalog) as database:
                return {
                    "catalog": catalog_label,
                    **plan_reprocess(database, adapter=adapter, limit=arguments.limit),
                }
        adapter = offline_replay_adapter(arguments.provider)
        with CatalogDatabase(arguments.catalog) as database:
            return {
                "catalog": catalog_label,
                **execute_reprocess(
                    database,
                    adapter,
                    raw_observation_ids=arguments.raw_id,
                    clock=utc_now,
                ),
            }
    if arguments.command == "tombstone":
        with CatalogDatabase(arguments.catalog) as database:
            if arguments.post is not None:
                result = tombstone_posts(database, list(arguments.post), reason=arguments.reason)
            else:
                result = tombstone_lookup_run(
                    database, arguments.lookup_run, reason=arguments.reason
                )
        return {"catalog": public_path(arguments.catalog), **result}
    with CatalogDatabase(arguments.catalog) as database:
        result = SeedMaterializationService(database).materialize(
            arguments.url,
            note=arguments.note,
            declared_md5=arguments.declared_md5,
            observed_at=utc_now(),
            file=arguments.file,
            media_root=arguments.media_root,
        )
    return {"catalog": catalog_label, **result}
