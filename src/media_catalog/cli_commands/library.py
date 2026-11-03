"""Artist library expansion: library."""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from media_catalog.adapter_factory import adapter_construction
from media_catalog.adapters.e621 import E621_INSTANCES
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.cli_commands.support import (
    add_json,
    add_library_plan_arguments,
    library_limits,
)
from media_catalog.database import CatalogDatabase
from media_catalog.library import (
    ArtistLibraryExpansionService,
    LibraryCountProbeService,
    LibraryExpansionQueryService,
    plan_library_expansion,
    replan_library_execution,
    target_capabilities,
)
from media_catalog.output import public_path

COMMANDS = ("library",)


def register(commands: argparse._SubParsersAction) -> None:
    library = commands.add_parser("library")
    library_commands = library.add_subparsers(dest="library_command", required=True)
    library_capabilities = library_commands.add_parser("capabilities")
    library_capabilities.add_argument("catalog", type=Path)
    library_capabilities.add_argument(
        "--target", metavar="ACCOUNT:ID|ATTRIBUTION:ID", required=True
    )
    add_json(library_capabilities)
    for name in ("plan", "probe", "run"):
        add_library_plan_arguments(library_commands.add_parser(name))
    library_resume = library_commands.add_parser("resume")
    library_resume.add_argument("catalog", type=Path)
    library_resume.add_argument("execution_id", type=int)
    add_json(library_resume)
    library_runs = library_commands.add_parser("runs")
    library_runs.add_argument("catalog", type=Path)
    library_runs.add_argument("--limit", type=int, default=100)
    library_runs.add_argument("--after", type=int)
    add_json(library_runs)
    library_show = library_commands.add_parser("show")
    library_show.add_argument("catalog", type=Path)
    library_show.add_argument("execution_id", type=int)
    add_json(library_show)


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    catalog_label = public_path(arguments.catalog)
    if arguments.library_command == "capabilities":
        return {
            "catalog": catalog_label,
            **target_capabilities(arguments.catalog, arguments.target),
        }
    if arguments.library_command in {"runs", "show"}:
        queries = LibraryExpansionQueryService(arguments.catalog)
        if arguments.library_command == "runs":
            return {
                "catalog": catalog_label,
                **queries.runs(limit=arguments.limit, after=arguments.after),
            }
        shown = queries.show(arguments.execution_id)
        if shown is None:
            raise ValueError("library expansion execution not found")
        return {"catalog": catalog_label, **shown}
    if arguments.library_command == "plan":
        plan = plan_library_expansion(
            arguments.catalog,
            arguments.seed,
            target=arguments.target,
            selection_note=arguments.selection_note,
            limits=library_limits(arguments),
        )
        return {"catalog": catalog_label, "status": "planned", **plan.as_dict()}
    with CatalogDatabase(arguments.catalog) as database:
        if arguments.library_command == "resume":
            plan = replan_library_execution(database, arguments.execution_id)
        else:
            plan = plan_library_expansion(
                database,
                arguments.seed,
                target=arguments.target,
                selection_note=arguments.selection_note,
                limits=library_limits(arguments),
            )
        if plan.selected is None:
            raise ValueError("library expansion target selection is ambiguous or unavailable")
        provider = plan.selected.target.provider
        if arguments.library_command == "probe":
            if provider == "pixiv":
                with PixivAdapter(require_auth=True) as adapter:
                    result = LibraryCountProbeService(database, pixiv_adapter=adapter).probe(plan)
            else:
                result = LibraryCountProbeService(database).probe(plan)
            return {"catalog": catalog_label, **result.as_dict()}
        if provider == "pixiv":
            with PixivAdapter(require_auth=True) as adapter:
                service = ArtistLibraryExpansionService(database, adapter)
                result = (
                    service.resume(plan, arguments.execution_id)
                    if arguments.library_command == "resume"
                    else service.run(plan)
                )
        elif provider in {"danbooru", "aibooru"} or provider in E621_INSTANCES:
            library_factory, library_interval = adapter_construction(provider)
            with httpx.Client() as client:
                adapter = library_factory(client)
                service = ArtistLibraryExpansionService(
                    database,
                    adapter,
                    minimum_interval_seconds=library_interval,
                )
                result = (
                    service.resume(plan, arguments.execution_id)
                    if arguments.library_command == "resume"
                    else service.run(plan)
                )
        else:
            raise ValueError(f"unsupported library expansion provider: {provider}")
        return {"catalog": catalog_label, **result.as_dict()}
