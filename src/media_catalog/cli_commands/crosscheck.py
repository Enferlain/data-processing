"""`catalog crosscheck`: whole-catalog batch provider cross-check (p1t)."""

from __future__ import annotations

import argparse
from pathlib import Path

from media_catalog.cli_commands.support import add_json
from media_catalog.crosscheck import (
    CORPORA,
    PROVIDERS,
    RECHECK_MODES,
    CrosscheckBudget,
    run_crosscheck,
)
from media_catalog.database import CatalogDatabase
from media_catalog.output import public_path

COMMANDS = ("crosscheck",)


def register(commands: argparse._SubParsersAction) -> None:
    parser = commands.add_parser(
        "crosscheck",
        description=(
            "Cross-check a selected corpus across live providers using the existing"
            " candidate-lookup machinery; durable, resumable, item-level reporting."
            " Budgets stop at item boundaries — re-run the same command to resume."
        ),
    )
    parser.add_argument("catalog", type=Path)
    parser.add_argument(
        "--corpus",
        choices=CORPORA,
        default="hash-material",
        help=(
            "hash-material (default): subjects with md5 or foreign-id query material;"
            " downloaded: posts with acquired assets; all: every post, including"
            " metadata-only bookmarks (reported as such)"
        ),
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDERS,
        action="append",
        help="limit providers (default: all configured lookup providers)",
    )
    parser.add_argument("--recheck", choices=RECHECK_MODES, default="unsearched")
    parser.add_argument("--stale-after", help="recheck=stale freshness window, e.g. 24h or 7d")
    parser.add_argument(
        "--max-requests",
        type=int,
        help="stop at an item boundary once total provider requests reach this",
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        help="stop at an item boundary once this many minutes elapse",
    )
    add_json(parser)


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    providers = tuple(arguments.provider) if arguments.provider else PROVIDERS
    with CatalogDatabase(arguments.catalog) as database:
        result = run_crosscheck(
            database,
            corpus=arguments.corpus,
            providers=providers,
            recheck=arguments.recheck,
            stale_after=arguments.stale_after,
            budget=CrosscheckBudget(
                max_requests=arguments.max_requests,
                max_minutes=arguments.max_minutes,
            ),
        )
    return {"catalog": public_path(arguments.catalog), **result}
