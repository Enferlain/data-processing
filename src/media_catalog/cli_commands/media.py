"""Media occurrence queries and asset/storage management: media, assets."""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from media_catalog.acquisition import (
    AcquisitionQueryService,
    AcquisitionService,
    HTTPTransferEngine,
    plan_acquisition,
    plan_expansion_acquisition,
)
from media_catalog.acquisition.planning import AcquisitionSelection
from media_catalog.cli_commands.support import (
    acquisition_limits,
    add_acquisition_limits,
    add_json,
    parse_acquisition_selections,
)
from media_catalog.database import CatalogDatabase
from media_catalog.media_queries import MediaQueryService
from media_catalog.output import public_path
from media_catalog.storage.adoption import adopt_assets, plan_adoption
from media_catalog.storage.cas import InspectionLimits
from media_catalog.storage.queries import (
    find_exact_duplicates,
    get_asset_detail,
    list_adoption_runs,
    list_assets,
    list_failed_adoption_items,
)
from media_catalog.storage.verification import verify_managed_storage

COMMANDS = ("media", "assets")


def register(commands: argparse._SubParsersAction) -> None:
    media = commands.add_parser("media")
    media_commands = media.add_subparsers(dest="media_command", required=True)
    media_list = media_commands.add_parser("list")
    media_list.add_argument("catalog", type=Path)
    media_list.add_argument("--platform")
    media_list.add_argument("--author", metavar="PLATFORM:NATIVE_ID")
    media_list.add_argument("--post", metavar="POST_ID|PLATFORM:NATIVE_ID")
    media_list.add_argument("--availability")
    media_list.add_argument("--linked", choices=("yes", "no"))
    media_list.add_argument("--limit", type=int, default=100)
    media_list.add_argument("--after", type=int)
    media_list.add_argument("--expansion-plan-id", type=int)
    add_json(media_list)
    media_show = media_commands.add_parser("show")
    media_show.add_argument("catalog", type=Path)
    media_show.add_argument("media_occurrence_id", type=int)
    add_json(media_show)

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
        add_json(command)

    download_plan = asset_commands.add_parser("download-plan")
    download_plan.add_argument("catalog", type=Path)
    selection = download_plan.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--select",
        action="append",
        metavar="OCCURRENCE[:VARIANT]",
    )
    selection.add_argument("--library-plan", type=int, metavar="PLAN_ID")
    download_plan.add_argument("--variant")
    download_plan.add_argument("--availability")
    download_plan.add_argument("--max-items", type=int, default=100)
    add_json(download_plan)

    download = asset_commands.add_parser("download")
    download.add_argument("catalog", type=Path)
    download.add_argument("--media-root", type=Path, required=True)
    download.add_argument(
        "--select",
        action="append",
        required=True,
        metavar="OCCURRENCE[:VARIANT]",
    )
    add_acquisition_limits(download)
    download.add_argument("--max-pixels", type=int, default=100_000_000)
    download.add_argument("--max-frames", type=int, default=100)
    add_json(download)

    download_runs = asset_commands.add_parser("download-runs")
    download_runs.add_argument("catalog", type=Path)
    download_runs.add_argument(
        "--status", choices=("running", "complete", "partial", "failed", "cancelled")
    )
    download_runs.add_argument("--limit", type=int, default=100)
    add_json(download_runs)

    download_show = asset_commands.add_parser("download-run-show")
    download_show.add_argument("catalog", type=Path)
    download_show.add_argument("run_id", type=int)
    add_json(download_show)

    download_retry = asset_commands.add_parser("download-retry")
    download_retry.add_argument("catalog", type=Path)
    download_retry.add_argument("run_id", type=int)
    download_retry.add_argument("--media-root", type=Path, required=True)
    download_retry.add_argument("--include-nonretryable", action="store_true")
    add_json(download_retry)

    asset_list = asset_commands.add_parser("list")
    asset_list.add_argument("catalog", type=Path)
    asset_list.add_argument("--sha256")
    add_json(asset_list)

    asset_show = asset_commands.add_parser("show")
    asset_show.add_argument("catalog", type=Path)
    asset_show.add_argument("asset_ref")
    add_json(asset_show)

    verify = asset_commands.add_parser("verify")
    verify.add_argument("catalog", type=Path)
    verify.add_argument("--media-root", type=Path, required=True)
    verify.add_argument("--managed-root-id", type=int)
    verify.add_argument("--max-bytes", type=int, default=128 * 1024 * 1024)
    verify.add_argument("--max-entries", type=int, default=100_000)
    add_json(verify)

    duplicates = asset_commands.add_parser("duplicates")
    duplicates.add_argument("catalog", type=Path)
    add_json(duplicates)

    runs = asset_commands.add_parser("runs")
    runs.add_argument("catalog", type=Path)
    runs.add_argument("--status", choices=("running", "complete", "partial", "failed", "cancelled"))
    add_json(runs)

    failures = asset_commands.add_parser("failures")
    failures.add_argument("catalog", type=Path)
    failures.add_argument("--run-id", type=int)
    add_json(failures)


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.command == "media":
        service = MediaQueryService(arguments.catalog)
        catalog_label = public_path(arguments.catalog)
        if arguments.media_command == "list":
            linked = None if arguments.linked is None else arguments.linked == "yes"
            return {
                "catalog": catalog_label,
                **service.list(
                    platform=arguments.platform,
                    author=arguments.author,
                    post=arguments.post,
                    availability=arguments.availability,
                    linked=linked,
                    limit=arguments.limit,
                    after=arguments.after,
                    expansion_plan_id=arguments.expansion_plan_id,
                ),
            }
        result = service.show(arguments.media_occurrence_id)
        if result is None:
            raise ValueError("media occurrence not found")
        return {"catalog": catalog_label, **result}
    return _execute_assets(arguments)


def _execute_assets(arguments: argparse.Namespace) -> dict[str, object]:
    catalog_label = public_path(arguments.catalog)
    if arguments.asset_command == "download-plan":
        if arguments.library_plan is not None:
            preview = plan_expansion_acquisition(
                arguments.catalog,
                arguments.library_plan,
                variant=arguments.variant,
                availability=arguments.availability or "available",
                max_items=arguments.max_items,
            )
        else:
            if arguments.availability is not None:
                raise ValueError("--availability requires --library-plan")
            # --variant with --select names the variant of every selected
            # occurrence: e621 occurrences expose explicit original/sample/
            # preview roles, and its policy refuses the generic default.
            # An explicit OCCURRENCE:VARIANT selection wins over the flag.
            selections = [
                selection
                if ":" in arguments.select[index] or arguments.variant is None
                else AcquisitionSelection(selection.media_occurrence_id, arguments.variant)
                for index, selection in enumerate(parse_acquisition_selections(arguments.select))
            ]
            preview = plan_acquisition(
                arguments.catalog,
                selections,
                max_items=arguments.max_items,
            )
        return {"catalog": catalog_label, "status": "planned", **preview.as_dict()}
    if arguments.asset_command in {"download-runs", "download-run-show"}:
        queries = AcquisitionQueryService(arguments.catalog)
        if arguments.asset_command == "download-runs":
            results = queries.runs(status=arguments.status, limit=arguments.limit)
            return {"catalog": catalog_label, "count": len(results), "results": results}
        result = queries.run(arguments.run_id)
        if result is None:
            raise ValueError("acquisition run not found")
        return {"catalog": catalog_label, **result}
    if arguments.asset_command == "download":
        if not arguments.media_root.is_dir():
            raise ValueError("managed media root must be an existing directory")
        limits = acquisition_limits(arguments)
        inspection = InspectionLimits(
            limits.max_item_bytes, arguments.max_pixels, arguments.max_frames
        )
        # Planning reads through the open database's supported snapshot, so
        # committed WAL frames from a concurrently writing process (e.g. the
        # labeling server) are planned against instead of rejected; the
        # explicitly read-only download-plan command keeps its stricter
        # no-WAL guarantee.
        with (
            CatalogDatabase(arguments.catalog) as database,
            httpx.Client() as client,
        ):
            preview = plan_acquisition(
                database,
                parse_acquisition_selections(arguments.select),
                max_items=limits.max_items,
            )
            result = AcquisitionService(
                database,
                HTTPTransferEngine(client),
                arguments.media_root,
                inspection_limits=inspection,
            ).execute(preview, limits)
        return {
            "catalog": catalog_label,
            "managed_root": public_path(arguments.media_root),
            **result.as_dict(),
        }
    if arguments.asset_command == "download-retry":
        if not arguments.media_root.is_dir():
            raise ValueError("managed media root must be an existing directory")
        with httpx.Client() as client, CatalogDatabase(arguments.catalog) as database:
            result = AcquisitionService(
                database, HTTPTransferEngine(client), arguments.media_root
            ).retry(
                arguments.run_id,
                include_nonretryable=arguments.include_nonretryable,
            )
        return {
            "catalog": catalog_label,
            "managed_root": public_path(arguments.media_root),
            **result.as_dict(),
        }
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
        limits = InspectionLimits(arguments.max_bytes, arguments.max_pixels, arguments.max_frames)
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
