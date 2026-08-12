from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import httpx

from media_catalog.acquisition import (
    AcquisitionQueryService,
    AcquisitionSelection,
    AcquisitionService,
    HTTPTransferEngine,
    plan_acquisition,
)
from media_catalog.adapters import AdapterOperation
from media_catalog.adapters.danbooru import (
    AIBOORU,
    DANBOORU,
    DanbooruAdapter,
    DanbooruCredentials,
)
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.candidate_lookup import (
    CandidateLookupQueryService,
    CandidateLookupService,
    LookupLimits,
    plan_candidate_lookup,
)
from media_catalog.database import CatalogDatabase
from media_catalog.discovery import DiscoveryService
from media_catalog.imports.x_likes_db import import_x_likes_database
from media_catalog.imports.xarchive import import_xarchive
from media_catalog.media_queries import MediaQueryService
from media_catalog.output import bounded_error, public_path, render_result
from media_catalog.records import AcquisitionLimits
from media_catalog.remote_queries import get_remote_run, list_remote_runs
from media_catalog.remote_sync import MetadataSyncService, SyncLimits
from media_catalog.storage.adoption import adopt_assets, plan_adoption
from media_catalog.storage.cas import AssetStorageError, InspectionLimits
from media_catalog.storage.queries import (
    find_exact_duplicates,
    get_asset_detail,
    list_adoption_runs,
    list_assets,
    list_failed_adoption_items,
)
from media_catalog.storage.verification import verify_managed_storage

LOOKUP_STRATEGIES = (
    "source_post_url",
    "external_post_id",
    "declared_md5",
    "verified_md5",
    "artist_exact_name",
    "artist_alias",
    "artist_text",
)


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit structured JSON")


def _add_sync_limits(parser: argparse.ArgumentParser, *, listing: bool) -> None:
    parser.add_argument("--max-requests", type=int, default=3 if listing else 1)
    parser.add_argument("--max-pages", type=int, default=2 if listing else 1)
    parser.add_argument("--max-records", type=int, default=500 if listing else 250)
    parser.add_argument("--max-seconds", type=int, default=60)
    parser.add_argument("--resume-from", type=int)
    _add_json(parser)


def _add_acquisition_limits(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-items", type=int, default=100)
    parser.add_argument("--max-item-bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--max-total-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--max-seconds", type=int, default=300)
    parser.add_argument("--max-redirects", type=int, default=5)
    parser.add_argument("--max-quarantine-bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--concurrency", type=int, choices=(1,), default=1)


def _add_lookup_limits(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-requests", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--max-results", type=int, default=200)
    parser.add_argument("--max-seconds", type=int, default=60)


def _parse_acquisition_selections(values: list[str]) -> list[AcquisitionSelection]:
    selections: list[AcquisitionSelection] = []
    for value in values:
        occurrence, separator, variant = value.partition(":")
        if not occurrence.isdecimal() or int(occurrence) <= 0:
            raise ValueError("selection must start with a positive occurrence id")
        if separator and not variant:
            raise ValueError("selection variant must not be empty")
        selections.append(AcquisitionSelection(int(occurrence), variant or "primary"))
    return selections


def _acquisition_limits(arguments: argparse.Namespace) -> AcquisitionLimits:
    return AcquisitionLimits(
        arguments.max_items,
        arguments.max_item_bytes,
        arguments.max_total_bytes,
        arguments.max_attempts,
        arguments.max_seconds,
        arguments.max_redirects,
        arguments.max_quarantine_bytes,
        arguments.concurrency,
    )


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
    _add_json(media_list)
    media_show = media_commands.add_parser("show")
    media_show.add_argument("catalog", type=Path)
    media_show.add_argument("media_occurrence_id", type=int)
    _add_json(media_show)

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

    download_plan = asset_commands.add_parser("download-plan")
    download_plan.add_argument("catalog", type=Path)
    download_plan.add_argument(
        "--select",
        action="append",
        required=True,
        metavar="OCCURRENCE[:VARIANT]",
    )
    download_plan.add_argument("--max-items", type=int, default=100)
    _add_json(download_plan)

    download = asset_commands.add_parser("download")
    download.add_argument("catalog", type=Path)
    download.add_argument("--media-root", type=Path, required=True)
    download.add_argument(
        "--select",
        action="append",
        required=True,
        metavar="OCCURRENCE[:VARIANT]",
    )
    _add_acquisition_limits(download)
    download.add_argument("--max-pixels", type=int, default=100_000_000)
    download.add_argument("--max-frames", type=int, default=100)
    _add_json(download)

    download_runs = asset_commands.add_parser("download-runs")
    download_runs.add_argument("catalog", type=Path)
    download_runs.add_argument(
        "--status", choices=("running", "complete", "partial", "failed", "cancelled")
    )
    download_runs.add_argument("--limit", type=int, default=100)
    _add_json(download_runs)

    download_show = asset_commands.add_parser("download-run-show")
    download_show.add_argument("catalog", type=Path)
    download_show.add_argument("run_id", type=int)
    _add_json(download_show)

    download_retry = asset_commands.add_parser("download-retry")
    download_retry.add_argument("catalog", type=Path)
    download_retry.add_argument("run_id", type=int)
    download_retry.add_argument("--media-root", type=Path, required=True)
    download_retry.add_argument("--include-nonretryable", action="store_true")
    _add_json(download_retry)

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

    metadata = commands.add_parser("metadata")
    metadata_commands = metadata.add_subparsers(dest="metadata_command", required=True)
    operations = {
        "pixiv-profile": False,
        "pixiv-artwork": False,
        "pixiv-account-artworks": True,
        "danbooru-post": False,
        "danbooru-artist": False,
        "danbooru-list": True,
        "aibooru-post": False,
        "aibooru-artist": False,
        "aibooru-list": True,
    }
    for name, listing in operations.items():
        command = metadata_commands.add_parser(name)
        command.add_argument("catalog", type=Path)
        command.add_argument("target")
        _add_sync_limits(command, listing=listing)
    remote_runs = metadata_commands.add_parser("runs")
    remote_runs.add_argument("catalog", type=Path)
    remote_runs.add_argument("--limit", type=int, default=100)
    _add_json(remote_runs)
    remote_show = metadata_commands.add_parser("run-show")
    remote_show.add_argument("catalog", type=Path)
    remote_show.add_argument("run_id", type=int)
    _add_json(remote_show)

    lookup = commands.add_parser("lookup")
    lookup_commands = lookup.add_subparsers(dest="lookup_command", required=True)
    for name in ("plan", "run"):
        command = lookup_commands.add_parser(name)
        command.add_argument("catalog", type=Path)
        command.add_argument("seed", metavar="ACCOUNT:ID|POST:ID")
        command.add_argument("--provider", choices=("danbooru", "aibooru"), required=True)
        command.add_argument(
            "--strategy", choices=LOOKUP_STRATEGIES, action="append", required=True
        )
        command.add_argument("--search-term")
        _add_lookup_limits(command)
        _add_json(command)
    lookup_resume = lookup_commands.add_parser("resume")
    lookup_resume.add_argument("catalog", type=Path)
    lookup_resume.add_argument("run_id", type=int)
    lookup_resume.add_argument("--provider", choices=("danbooru", "aibooru"), required=True)
    _add_lookup_limits(lookup_resume)
    _add_json(lookup_resume)
    lookup_runs = lookup_commands.add_parser("runs")
    lookup_runs.add_argument("catalog", type=Path)
    lookup_runs.add_argument("--status", choices=("running", "complete", "paused", "failed"))
    lookup_runs.add_argument("--limit", type=int, default=50)
    lookup_runs.add_argument("--after", type=int)
    _add_json(lookup_runs)
    lookup_show = lookup_commands.add_parser("show")
    lookup_show.add_argument("catalog", type=Path)
    lookup_show.add_argument("run_id", type=int)
    lookup_show.add_argument("--result-limit", type=int, default=100)
    lookup_show.add_argument("--result-after", type=int)
    _add_json(lookup_show)
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
                ),
            }
        result = service.show(arguments.media_occurrence_id)
        if result is None:
            raise ValueError("media occurrence not found")
        return {"catalog": catalog_label, **result}
    if arguments.command == "assets":
        catalog_label = public_path(arguments.catalog)
        if arguments.asset_command == "download-plan":
            preview = plan_acquisition(
                arguments.catalog,
                _parse_acquisition_selections(arguments.select),
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
            limits = _acquisition_limits(arguments)
            preview = plan_acquisition(
                arguments.catalog,
                _parse_acquisition_selections(arguments.select),
                max_items=limits.max_items,
            )
            inspection = InspectionLimits(
                limits.max_item_bytes, arguments.max_pixels, arguments.max_frames
            )
            with httpx.Client() as client, CatalogDatabase(arguments.catalog) as database:
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
    if arguments.command == "metadata":
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
        else:
            instance = AIBOORU if command.startswith("aibooru-") else DANBOORU
            operation = (
                AdapterOperation.FETCH_POST
                if command.endswith("-post")
                else (
                    AdapterOperation.FETCH_ATTRIBUTION
                    if command.endswith("-artist")
                    else AdapterOperation.LIST_ACCOUNT_POSTS
                )
            )
            credentials = DanbooruCredentials.from_environment(instance)
            with httpx.Client() as client, CatalogDatabase(arguments.catalog) as database:
                adapter = DanbooruAdapter(instance, client=client, credentials=credentials)
                result = MetadataSyncService(
                    database,
                    adapter,
                    minimum_interval_seconds=instance.minimum_interval_seconds,
                ).synchronize(
                    operation,
                    arguments.target,
                    limits=limits,
                    resume_from_run_id=arguments.resume_from,
                )
        return {"catalog": catalog_label, **result.as_dict()}
    if arguments.command == "lookup":
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
        instance = DANBOORU if arguments.provider == "danbooru" else AIBOORU
        if arguments.lookup_command == "plan":
            plan = plan_candidate_lookup(
                arguments.catalog,
                arguments.seed,
                instance,
                tuple(arguments.strategy),
                limits=limits,
                search_term=arguments.search_term,
            )
            return {"catalog": catalog_label, "status": "planned", **plan.as_dict()}
        credentials = DanbooruCredentials.from_environment(instance)
        with httpx.Client() as client, CatalogDatabase(arguments.catalog) as database:
            adapter = DanbooruAdapter(instance, client=client, credentials=credentials)
            service = CandidateLookupService(
                database,
                adapter,
                minimum_interval_seconds=instance.minimum_interval_seconds,
            )
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
    if (
        arguments.command == "assets"
        and arguments.asset_command not in {"download-plan", "download-runs", "download-run-show"}
        and result.get("status") in {"partial", "failed", "issues"}
    ):
        raise SystemExit(2)
    if (
        arguments.command == "metadata"
        and arguments.metadata_command not in {"runs", "run-show"}
        and result.get("status") in {"paused", "failed"}
    ):
        raise SystemExit(2)
    lookup_results = result.get("results")
    if (
        arguments.command == "lookup"
        and arguments.lookup_command in {"run", "resume"}
        and (
            result.get("status") in {"paused", "failed"}
            or (
                isinstance(lookup_results, list)
                and any(
                    item.get("status") in {"paused", "failed"}
                    for item in lookup_results
                    if isinstance(item, dict)
                )
            )
        )
    ):
        raise SystemExit(2)
