"""Projection exports and work materialization: export, works."""

from __future__ import annotations

import argparse
from pathlib import Path

from media_catalog.cli_commands.support import add_json, utc_now
from media_catalog.database import CatalogDatabase
from media_catalog.output import public_path
from media_catalog.projections import DEFAULT_LIMIT, FORMATS, plan_export, run_export
from media_catalog.relationships import materialize_works

_KIND_CHOICES = (
    "assets",
    "attribution-disagreements",
    "post-field-sources",
    "posts",
    "works",
)


COMMANDS = ("export", "works")


def register(commands: argparse._SubParsersAction) -> None:
    export = commands.add_parser("export")
    export_commands = export.add_subparsers(dest="export_command", required=True)
    export_plan = export_commands.add_parser("plan")
    export_plan.add_argument("catalog", type=Path)
    export_plan.add_argument("--kind", choices=_KIND_CHOICES, required=True)
    export_plan.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    export_plan.add_argument(
        "--platform", help="posts only: restrict the projection to one platform"
    )
    export_plan.add_argument(
        "--as-of",
        metavar="TIMESTAMP",
        help="post-field-sources only: reconstruct under an ISO-8601 Z evidence cutoff",
    )
    add_json(export_plan)
    export_run = export_commands.add_parser("run")
    export_run.add_argument("catalog", type=Path)
    export_run.add_argument("--kind", choices=_KIND_CHOICES, required=True)
    export_run.add_argument(
        "--out-dir", type=Path, default=Path("."), help="directory for data files and manifest"
    )
    export_run.add_argument("--format", choices=("jsonl", "csv"), action="append", dest="formats")
    export_run.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    export_run.add_argument(
        "--platform", help="posts only: restrict the projection to one platform"
    )
    export_run.add_argument(
        "--as-of",
        metavar="TIMESTAMP",
        help="post-field-sources only: reconstruct under an ISO-8601 Z evidence cutoff",
    )
    add_json(export_run)

    works = commands.add_parser("works")
    works_commands = works.add_subparsers(dest="works_command", required=True)
    works_materialize = works_commands.add_parser("materialize")
    works_materialize.add_argument("catalog", type=Path)
    add_json(works_materialize)


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.command == "works":
        catalog_label = public_path(arguments.catalog)
        with CatalogDatabase(arguments.catalog) as database:
            return {
                "catalog": catalog_label,
                **materialize_works(database, clock=utc_now),
            }
    catalog_label = public_path(arguments.catalog)
    formats = tuple(arguments.formats) if getattr(arguments, "formats", None) else FORMATS
    if arguments.export_command == "plan":
        return {
            "catalog": catalog_label,
            **plan_export(
                arguments.catalog,
                kind=arguments.kind,
                limit=arguments.limit,
                platform=arguments.platform,
                as_of=arguments.as_of,
            ),
        }
    return {
        "catalog": catalog_label,
        **run_export(
            arguments.catalog,
            kind=arguments.kind,
            out_dir=arguments.out_dir,
            formats=formats,
            limit=arguments.limit,
            platform=arguments.platform,
            as_of=arguments.as_of,
            clock=utc_now,
        ),
    }
