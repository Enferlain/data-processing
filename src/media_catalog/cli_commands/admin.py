"""Catalog administration and health surfaces: init, schema, doctor, stats,
search, adapter-doctor."""

from __future__ import annotations

import argparse
from pathlib import Path

from media_catalog.cli_commands.support import add_json
from media_catalog.database import CatalogDatabase
from media_catalog.doctor import DOCTOR_PLATFORMS, render_report, run_doctor
from media_catalog.output import public_path

COMMANDS = ("init", "schema", "doctor", "adapter-doctor", "stats", "search")


def register(commands: argparse._SubParsersAction) -> None:
    for name in ("init", "schema", "doctor"):
        command = commands.add_parser(name)
        command.add_argument("catalog", type=Path)
        add_json(command)
    adapter_doctor = commands.add_parser(
        "adapter-doctor",
        description="Verify every adapter against its captured contract; --live probes providers",
    )
    adapter_doctor.add_argument("--live", action="store_true")
    adapter_doctor.add_argument("--platform", action="append", choices=DOCTOR_PLATFORMS)
    add_json(adapter_doctor)
    stats = commands.add_parser("stats")
    stats.add_argument("catalog", type=Path)
    stats.add_argument("--event", choices=("liked", "bookmarked"))
    add_json(stats)
    search = commands.add_parser("search")
    search.add_argument("catalog", type=Path)
    search.add_argument("query")
    search.add_argument("--event", choices=("liked", "bookmarked"))
    add_json(search)


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.command == "init":
        with CatalogDatabase(arguments.catalog) as database:
            return {
                "status": "initialized",
                "catalog": public_path(database.path),
                **database.schema_info(),
            }
    if arguments.command == "adapter-doctor":
        report = run_doctor(live=arguments.live, platforms=tuple(arguments.platform or ()))
        if not arguments.json:
            print(render_report(report, live=arguments.live))
        result = report.as_dict()
        if not report.ok:
            result["status"] = "failed"
        else:
            result["status"] = "ok"
        return result
    with CatalogDatabase(arguments.catalog) as database:
        if arguments.command == "schema":
            return {"catalog": public_path(database.path), **database.schema_info()}
        if arguments.command == "doctor":
            # The catalog doctor reports storage integrity and the
            # adapters' offline contract health together; the full
            # per-case detail and live probing stay on adapter-doctor.
            # The top-level "ok" reflects storage only (the database
            # spread comes last); adapter health is the "adapters"
            # summary.
            adapters = run_doctor()
            adapter_summary = {
                "ok": adapters.ok,
                "surfaces": {surface.platform: surface.ok for surface in adapters.surfaces},
                "failures": [
                    f"{surface.platform}: {reason}"
                    for surface in adapters.surfaces
                    for reason in surface.failure_reasons
                ],
                "errors": list(adapters.errors),
            }
            return {
                "catalog": public_path(database.path),
                "adapters": adapter_summary,
                **database.doctor(),
            }
        if arguments.command == "stats":
            return {
                "catalog": public_path(database.path),
                **database.stats(event_type=arguments.event),
            }
        return {
            "catalog": public_path(database.path),
            **database.search(arguments.query, event_type=arguments.event),
        }
