"""Candidate lookup planning and execution: lookup."""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from media_catalog.adapter_factory import adapter_construction
from media_catalog.adapters import LookupPlanConfiguration
from media_catalog.adapters.danbooru import AIBOORU, DANBOORU
from media_catalog.adapters.e621 import E621_INSTANCES
from media_catalog.adapters.gelbooru import GELBOORU_INSTANCES
from media_catalog.candidate_lookup import (
    CandidateLookupQueryService,
    CandidateLookupService,
    LookupLimits,
    plan_candidate_lookup,
)
from media_catalog.cli_commands.support import add_json, add_lookup_limits
from media_catalog.database import CatalogDatabase
from media_catalog.output import public_path

LOOKUP_STRATEGIES = (
    "source_post_url",
    "external_post_id",
    "declared_md5",
    "verified_md5",
    "artist_exact_name",
    "artist_alias",
    "artist_text",
)


COMMANDS = ("lookup",)


def register(commands: argparse._SubParsersAction) -> None:
    lookup = commands.add_parser("lookup")
    lookup_commands = lookup.add_subparsers(dest="lookup_command", required=True)
    for name in ("plan", "run"):
        command = lookup_commands.add_parser(name)
        command.add_argument("catalog", type=Path)
        command.add_argument("seed", metavar="ACCOUNT:ID|POST:ID")
        command.add_argument(
            "--provider",
            choices=("danbooru", "aibooru", "e621", "gelbooru"),
            required=True,
        )
        command.add_argument(
            "--strategy", choices=LOOKUP_STRATEGIES, action="append", required=True
        )
        command.add_argument("--search-term")
        add_lookup_limits(command)
        add_json(command)
    lookup_resume = lookup_commands.add_parser("resume")
    lookup_resume.add_argument("catalog", type=Path)
    lookup_resume.add_argument("run_id", type=int)
    lookup_resume.add_argument(
        "--provider", choices=("danbooru", "aibooru", "e621", "gelbooru"), required=True
    )
    add_lookup_limits(lookup_resume)
    add_json(lookup_resume)
    lookup_runs = lookup_commands.add_parser("runs")
    lookup_runs.add_argument("catalog", type=Path)
    lookup_runs.add_argument("--status", choices=("running", "complete", "paused", "failed"))
    lookup_runs.add_argument("--limit", type=int, default=50)
    lookup_runs.add_argument("--after", type=int)
    add_json(lookup_runs)
    lookup_show = lookup_commands.add_parser("show")
    lookup_show.add_argument("catalog", type=Path)
    lookup_show.add_argument("run_id", type=int)
    lookup_show.add_argument("--result-limit", type=int, default=100)
    lookup_show.add_argument("--result-after", type=int)
    add_json(lookup_show)


def _execute_lookup(
    arguments: argparse.Namespace,
    catalog_label: str,
    service: CandidateLookupService,
    limits: LookupLimits,
) -> dict[str, object]:
    if arguments.lookup_command == "run":
        plan = service.plan(
            arguments.seed,
            tuple(arguments.strategy),
            limits=limits,
            search_term=arguments.search_term,
        )
        results = service.execute(plan)
        return {
            "catalog": catalog_label,
            "count": len(results),
            "results": [result.as_dict() for result in results],
        }
    result = service.resume(arguments.run_id, limits=limits)
    return {"catalog": catalog_label, **result.as_dict()}


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    catalog_label = public_path(arguments.catalog)
    if arguments.lookup_command in {"runs", "show"}:
        queries = CandidateLookupQueryService(arguments.catalog)
        if arguments.lookup_command == "runs":
            return {
                "catalog": catalog_label,
                **queries.runs(
                    status=arguments.status,
                    limit=arguments.limit,
                    after=arguments.after,
                ),
            }
        result = queries.show(
            arguments.run_id,
            result_limit=arguments.result_limit,
            result_after=arguments.result_after,
        )
        if result is None:
            raise ValueError("candidate lookup run not found")
        return {"catalog": catalog_label, **result}
    limits = LookupLimits(
        arguments.max_requests,
        arguments.max_pages,
        arguments.max_results,
        arguments.max_seconds,
    )
    if arguments.lookup_command == "plan":
        registry_instance = E621_INSTANCES.get(arguments.provider) or GELBOORU_INSTANCES.get(
            arguments.provider
        )
        plan_configuration: LookupPlanConfiguration = (
            registry_instance
            if registry_instance is not None
            else DANBOORU
            if arguments.provider == "danbooru"
            else AIBOORU
        )
        plan = plan_candidate_lookup(
            arguments.catalog,
            arguments.seed,
            plan_configuration,
            tuple(arguments.strategy),
            limits=limits,
            search_term=arguments.search_term,
        )
        return {"catalog": catalog_label, "status": "planned", **plan.as_dict()}
    lookup_factory, lookup_interval = adapter_construction(arguments.provider)
    with httpx.Client() as client, CatalogDatabase(arguments.catalog) as database:
        adapter = lookup_factory(client)
        service = CandidateLookupService(
            database,
            adapter,
            minimum_interval_seconds=lookup_interval,
        )
        return _execute_lookup(arguments, catalog_label, service, limits)
