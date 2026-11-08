"""Catalog administration and health surfaces: init, schema, doctor, stats,
search, adapter-doctor, backup, restore."""

from __future__ import annotations

import argparse
from pathlib import Path

from media_catalog.backup import backup_catalog, backup_doctor_section, restore_catalog
from media_catalog.cli_commands.support import add_json
from media_catalog.database import CatalogDatabase
from media_catalog.doctor import DOCTOR_PLATFORMS, render_report, run_doctor
from media_catalog.output import public_path

COMMANDS = (
    "init",
    "schema",
    "doctor",
    "adapter-doctor",
    "stats",
    "search",
    "backup",
    "restore",
)


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
    backup = commands.add_parser(
        "backup",
        description=(
            "Online consistent catalog snapshot (VACUUM INTO) with a verified"
            " manifest; media roots are recorded, not copied"
        ),
    )
    backup.add_argument("catalog", type=Path)
    backup.add_argument(
        "--dest",
        type=Path,
        help="backup directory (default: <catalog-stem>-backups/ beside the catalog)",
    )
    backup.add_argument(
        "--keep",
        type=int,
        help="keep only the newest N complete backups (never prunes the newest)",
    )
    add_json(backup)
    restore = commands.add_parser(
        "restore",
        description="Verify a backup's manifest digest, then restore it to a new catalog path",
    )
    restore.add_argument("backup", type=Path)
    restore.add_argument("--to", type=Path, required=True)
    restore.add_argument("--force", action="store_true", help="overwrite an existing target")
    restore.add_argument(
        "--verify",
        action="store_true",
        help="run integrity and foreign-key checks on the restored catalog",
    )
    restore.add_argument(
        "--media-root",
        type=Path,
        action="append",
        default=[],
        help="verify this managed media tree against the restored catalog (repeatable)",
    )
    add_json(restore)


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
    if arguments.command == "backup":
        return {
            "catalog": public_path(arguments.catalog),
            **backup_catalog(
                arguments.catalog,
                destination=arguments.dest,
                keep=arguments.keep,
            ).as_dict(),
        }
    if arguments.command == "restore":
        return {
            **restore_catalog(
                arguments.backup,
                to=arguments.to,
                force=arguments.force,
                verify=arguments.verify,
                media_roots=tuple(arguments.media_root),
            ).as_dict()
        }
    with CatalogDatabase(arguments.catalog) as database:
        if arguments.command == "schema":
            return {"catalog": public_path(database.path), **database.schema_info()}
        if arguments.command == "doctor":
            # The catalog doctor reports storage integrity, backup state,
            # and the adapters' offline contract health together; the full
            # per-case detail and live probing stay on adapter-doctor.
            # The top-level "ok" reflects storage and backup digest health
            # (the database spread comes last, backup drift after it);
            # adapter health is the "adapters" summary.
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
            result = {
                "catalog": public_path(database.path),
                "adapters": adapter_summary,
                **database.doctor(),
                **backup_doctor_section(database.path),
            }
            backup_section = result.get("backup")
            if isinstance(backup_section, dict) and backup_section.get("ok") is False:
                result["ok"] = False
            return result
        if arguments.command == "stats":
            return {
                "catalog": public_path(database.path),
                **database.stats(event_type=arguments.event),
            }
        return {
            "catalog": public_path(database.path),
            **database.search(arguments.query, event_type=arguments.event),
        }
