from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from media_catalog.asset_adoption import (
    adopt_assets,
    find_exact_duplicates,
    get_asset_detail,
    list_adoption_runs,
    list_assets,
    list_failed_adoption_items,
    plan_adoption,
)
from media_catalog.asset_storage import AssetStorageError, InspectionLimits
from media_catalog.asset_verification import verify_managed_storage
from media_catalog.database import CatalogDatabase
from media_catalog.discovery import DiscoveryService
from media_catalog.imports.x_likes_db import import_x_likes_database
from media_catalog.imports.xarchive import import_xarchive
from media_catalog.output import bounded_error, public_path, render_result


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit structured JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catalog", description="Local cross-platform media catalog"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name in ("init", "schema", "doctor"):
        command = commands.add_parser(name)
        command.add_argument("catalog", type=Path)
        _add_json(command)

    stats = commands.add_parser("stats")
    stats.add_argument("catalog", type=Path)
    stats.add_argument("--event", choices=("liked", "bookmarked"))
    _add_json(stats)

    search = commands.add_parser("search")
    search.add_argument("catalog", type=Path)
    search.add_argument("query")
    search.add_argument("--event", choices=("liked", "bookmarked"))
    _add_json(search)

    ingest = commands.add_parser("ingest")
    sources = ingest.add_subparsers(dest="source_kind", required=True)
    for source_kind in ("x-likes-db", "xarchive"):
        source = sources.add_parser(source_kind)
        source.add_argument("source", type=Path)
        source.add_argument("--catalog", type=Path, required=True)
        _add_json(source)

    discover = commands.add_parser("discover-links")
    discover.add_argument("catalog", type=Path)
    _add_json(discover)

    links = commands.add_parser("links")
    links.add_argument("catalog", type=Path)
    links.add_argument("--subject-kind", choices=("account", "post"))
    links.add_argument("--subject-id", type=int)
    links.add_argument("--source-context")
    links.add_argument("--platform")
    links.add_argument("--instance")
    links.add_argument("--object-kind", choices=("account", "post", "artist", "media_asset"))
    links.add_argument(
        "--state", choices=("recognized", "unresolved", "invalid", "redirect_required")
    )
    _add_json(links)

    matches = commands.add_parser("matches")
    matches.add_argument("catalog", type=Path)
    matches.add_argument("--kind", choices=("account", "post"))
    matches.add_argument("--state", choices=("pending", "confirmed", "rejected"))
    _add_json(matches)

    show = commands.add_parser("match-show")
    show.add_argument("catalog", type=Path)
    show.add_argument("match_ref")
    _add_json(show)

    review = commands.add_parser("match-review")
    review.add_argument("catalog", type=Path)
    review.add_argument("match_ref")
    review.add_argument("--decision", choices=("confirm", "reject", "pending"), required=True)
    review.add_argument("--note")
    review.add_argument("--expected-generation", type=int)
    review.add_argument("--expected-revision", type=int)
    _add_json(review)

    assets = commands.add_parser("assets")
    asset_commands = assets.add_subparsers(dest="asset_command", required=True)
    for name in ("plan", "adopt"):
        command = asset_commands.add_parser(name)
        command.add_argument("catalog", type=Path)
        command.add_argument("--source-root", type=Path, required=True)
        command.add_argument("--media-root", type=Path, required=True)
        command.add_argument("--max-files", type=int, dest="limit")
        command.add_argument("--path-prefix")
        command.add_argument("--max-bytes", type=int, default=128 * 1024 * 1024)
        if name == "adopt":
            command.add_argument("--max-pixels", type=int, default=100_000_000)
            command.add_argument("--max-frames", type=int, default=100)
        _add_json(command)

    asset_list = asset_commands.add_parser("list")
    asset_list.add_argument("catalog", type=Path)
    asset_list.add_argument("--sha256")
    _add_json(asset_list)

    asset_show = asset_commands.add_parser("show")
    asset_show.add_argument("catalog", type=Path)
    asset_show.add_argument("asset_ref")
    _add_json(asset_show)

    verify = asset_commands.add_parser("verify")
    verify.add_argument("catalog", type=Path)
    verify.add_argument("--media-root", type=Path, required=True)
    verify.add_argument("--managed-root-id", type=int)
    verify.add_argument("--max-bytes", type=int, default=128 * 1024 * 1024)
    verify.add_argument("--max-entries", type=int, default=100_000)
    _add_json(verify)

    duplicates = asset_commands.add_parser("duplicates")
    duplicates.add_argument("catalog", type=Path)
    _add_json(duplicates)

    runs = asset_commands.add_parser("runs")
    runs.add_argument("catalog", type=Path)
    runs.add_argument("--status", choices=("running", "complete", "partial", "failed", "cancelled"))
    _add_json(runs)

    failures = asset_commands.add_parser("failures")
    failures.add_argument("catalog", type=Path)
    failures.add_argument("--run-id", type=int)
    _add_json(failures)
    return parser


def _run(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.command == "init":
        with CatalogDatabase(arguments.catalog) as database:
            return {
                "status": "initialized",
                "catalog": public_path(database.path),
                **database.schema_info(),
            }
    if arguments.command in {"schema", "doctor", "stats", "search"}:
        with CatalogDatabase(arguments.catalog) as database:
            if arguments.command == "schema":
                return {"catalog": public_path(database.path), **database.schema_info()}
            if arguments.command == "doctor":
                return {"catalog": public_path(database.path), **database.doctor()}
            if arguments.command == "stats":
                return {
                    "catalog": public_path(database.path),
                    **database.stats(event_type=arguments.event),
                }
            return {
                "catalog": public_path(database.path),
                **database.search(arguments.query, event_type=arguments.event),
            }
    if arguments.command == "ingest":
        if not arguments.source.is_file():
            raise FileNotFoundError(f"source file not found: {public_path(arguments.source)}")
        with CatalogDatabase(arguments.catalog) as database:
            importer = (
                import_xarchive if arguments.source_kind == "xarchive" else import_x_likes_database
            )
            return {
                "catalog": public_path(database.path),
                **importer(database, arguments.source).as_dict(),
            }
    if arguments.command in {
        "discover-links",
        "links",
        "matches",
        "match-show",
        "match-review",
    }:
        with CatalogDatabase(arguments.catalog) as database:
            service = DiscoveryService(database)
            if arguments.command == "discover-links":
                return {"catalog": public_path(database.path), **service.discover().as_dict()}
            if arguments.command == "links":
                return {
                    "catalog": public_path(database.path),
                    **service.links(
                        subject_kind=arguments.subject_kind,
                        subject_id=arguments.subject_id,
                        source_context=arguments.source_context,
                        platform=arguments.platform,
                        instance=arguments.instance,
                        object_kind=arguments.object_kind,
                        state=arguments.state,
                    ),
                }
            if arguments.command == "matches":
                return {
                    "catalog": public_path(database.path),
                    **service.candidates(kind=arguments.kind, state=arguments.state),
                }
            if arguments.command == "match-show":
                return {
                    "catalog": public_path(database.path),
                    **service.candidate(arguments.match_ref),
                }
            decisions = {"confirm": "confirmed", "reject": "rejected", "pending": "pending"}
            return {
                "catalog": public_path(database.path),
                **service.review(
                    arguments.match_ref,
                    decisions[arguments.decision],
                    note=arguments.note,
                    expected_generation=arguments.expected_generation,
                    expected_revision=arguments.expected_revision,
                ),
            }
    if arguments.command == "assets":
        catalog_label = public_path(arguments.catalog)
        if arguments.asset_command == "plan":
            return {
                "catalog": catalog_label,
                "status": "planned",
                **plan_adoption(
                    arguments.catalog,
                    arguments.source_root,
                    arguments.media_root,
                    path_prefix=arguments.path_prefix,
                    limit=arguments.limit,
                    max_bytes=arguments.max_bytes,
                ).as_dict(),
            }
        if arguments.asset_command == "adopt":
            limits = InspectionLimits(
                arguments.max_bytes, arguments.max_pixels, arguments.max_frames
            )
            with CatalogDatabase(arguments.catalog) as database:
                return {
                    "catalog": catalog_label,
                    "source_root": public_path(arguments.source_root),
                    "managed_root": public_path(arguments.media_root),
                    **adopt_assets(
                        database,
                        arguments.source_root,
                        arguments.media_root,
                        path_prefix=arguments.path_prefix,
                        limit=arguments.limit,
                        limits=limits,
                    ).as_dict(),
                }
        if arguments.asset_command == "verify":
            return {
                "catalog": catalog_label,
                "managed_root": public_path(arguments.media_root),
                **verify_managed_storage(
                    arguments.catalog,
                    arguments.media_root,
                    managed_root_id=arguments.managed_root_id,
                    max_bytes=arguments.max_bytes,
                    max_entries=arguments.max_entries,
                ).as_dict(),
            }
        if arguments.asset_command == "list":
            results = list_assets(arguments.catalog, sha256=arguments.sha256)
        elif arguments.asset_command == "show":
            identifier: int | str = (
                int(arguments.asset_ref) if arguments.asset_ref.isdecimal() else arguments.asset_ref
            )
            result = get_asset_detail(arguments.catalog, identifier)
            if result is None:
                raise ValueError("asset not found")
            return {"catalog": catalog_label, **result}
        elif arguments.asset_command == "duplicates":
            results = find_exact_duplicates(arguments.catalog)
        elif arguments.asset_command == "runs":
            results = list_adoption_runs(arguments.catalog, status=arguments.status)
        else:
            results = list_failed_adoption_items(arguments.catalog, run_id=arguments.run_id)
        return {"catalog": catalog_label, "count": len(results), "results": results}
    raise NotImplementedError(f"{arguments.command} is planned but not implemented yet")


def main(argv: list[str] | None = None) -> None:
    arguments = build_parser().parse_args(argv)
    try:
        result = _run(arguments)
    except (AssetStorageError, OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        private_paths = tuple(
            value
            for name in ("source", "catalog", "source_root", "media_root")
            if isinstance((value := getattr(arguments, name, None)), Path)
        )
        message = bounded_error(error, private_paths=private_paths)
        if arguments.json:
            raise SystemExit(json.dumps({"error": message}, ensure_ascii=False)) from error
        raise SystemExit(f"error: {message}") from error
    print(render_result(result, as_json=arguments.json))
    if arguments.command == "assets" and result.get("status") in {"partial", "failed", "issues"}:
        raise SystemExit(2)
