"""Catalog data maintenance: reprocess (offline replay), seed creation."""

from __future__ import annotations

import argparse
import time
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


COMMANDS = ("reprocess", "seed", "tombstone", "label", "index")


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

    label = commands.add_parser(
        "label",
        description="Interactive local labeling UI for pair calibration",
    )
    label.add_argument("catalog", type=Path)
    label.add_argument("--media-root", type=Path, required=True)
    label.add_argument("--port", type=int, default=8765)
    label.add_argument(
        "--revisit-unsure",
        action="store_true",
        help="Revisit ready unsure pairs; preserve and defer labels with missing media",
    )

    index_cmd = commands.add_parser(
        "index",
        description=(
            "Local search index maintenance: register/list/import provider"
            " lookup projections (discovery only reads them)"
        ),
    )
    index_commands = index_cmd.add_subparsers(dest="index_command", required=True)
    index_register = index_commands.add_parser(
        "register", description="Bind a lookup-v1 projection to a discovery target"
    )
    index_register.add_argument("catalog", type=Path)
    index_register.add_argument(
        "--provider", required=True, help="provider platform key (e621, danbooru, ...)"
    )
    index_register.add_argument(
        "--path",
        type=Path,
        help="projection file (default: <catalog-stem>-indexes/<provider>/lookup.sqlite)",
    )
    index_register.add_argument(
        "--name", help="target name (default: the provider key); the identity, not the path"
    )
    add_json(index_register)
    index_list = index_commands.add_parser("list", description="Show registered indexes")
    index_list.add_argument("catalog", type=Path)
    add_json(index_list)
    index_prune = index_commands.add_parser(
        "prune",
        description=(
            "Report (and with --apply, delete) download artifacts no registered"
            " projection references: stale .part temp files and superseded exports"
        ),
    )
    index_prune.add_argument("catalog", type=Path)
    index_prune.add_argument("--provider", required=True, help="provider platform key")
    index_prune.add_argument(
        "--apply", action="store_true", help="delete the reported files (default: report only)"
    )
    add_json(index_prune)
    index_import = index_commands.add_parser(
        "import",
        description=(
            "Build a lookup-v1 projection from a raw provider artifact"
            " (--download fetches it from the provider's export listing,"
            " checksum-verified)"
        ),
    )
    index_import.add_argument("catalog", type=Path)
    index_import.add_argument(
        "--provider",
        required=True,
        choices=("e621", "danbooru"),
        help="artifact source provider (danbooru: posts-snapshot.parquet via --artifact)",
    )
    artifact_source = index_import.add_mutually_exclusive_group(required=True)
    artifact_source.add_argument(
        "--artifact", type=Path, help="downloaded provider artifact (kept untouched)"
    )
    artifact_source.add_argument(
        "--download",
        action="store_true",
        help="fetch the complete export from the provider (e621 db_exports listing),"
        " verify its published checksum, retain it under"
        " <catalog-stem>-indexes/<provider>/downloads/ — the transfer is never bounded"
        " by --max-records, which limits only the import",
    )
    index_import.add_argument(
        "--export",
        choices=("posts", "artists"),
        default="posts",
        help="which e621 db export to import (posts: post lookups; artists:"
        " artist_identifier resolution, default target <provider>-artists)",
    )
    index_import.add_argument(
        "--max-records",
        type=int,
        help="bounded import for testing: only the first N export rows"
        " (the artifact download itself is never bounded)",
    )
    index_import.add_argument(
        "--checksum", help="published SHA-256 of the artifact; verified before building"
    )
    index_import.add_argument(
        "--path",
        type=Path,
        help="projection destination (default: <catalog-stem>-indexes/<provider>/lookup.sqlite;"
        " artists: <catalog-stem>-indexes/<provider>-artists/lookup.sqlite)",
    )
    add_json(index_import)


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
    if arguments.command == "label":
        from media_catalog.labeling.server import serve

        serve(
            arguments.catalog,
            arguments.media_root,
            port=arguments.port,
            revisit_unsure=arguments.revisit_unsure,
        )
        return {"status": "stopped"}
    if arguments.command == "index":
        return _execute_index(arguments)
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


def _default_downloads_dir(catalog: Path, provider: str) -> Path:
    return catalog.parent / f"{catalog.stem}-indexes" / provider / "downloads"


def _default_index_path(catalog: Path, provider: str) -> Path:
    return catalog.parent / f"{catalog.stem}-indexes" / provider / "lookup.sqlite"


def _upsert_registration(
    database: CatalogDatabase,
    *,
    name: str,
    provider: str,
    path: Path,
    revision: str,
) -> None:
    now = utc_now()
    existing = database.connection.execute(
        "SELECT search_index_registration_id, registered_at"
        " FROM search_index_registrations WHERE target_name = ?",
        (name,),
    ).fetchone()
    if existing is None:
        database.connection.execute(
            """INSERT INTO search_index_registrations
                   (target_name, provider, index_format, private_path,
                    snapshot_revision, registered_at)
               VALUES (?, ?, 'lookup-v1', ?, ?, ?)""",
            (name, provider, str(path), revision, now),
        )
    else:
        # Path and revision are plumbing; the target identity (name) and its
        # registration history are preserved across moves and refreshes.
        database.connection.execute(
            """UPDATE search_index_registrations
                  SET provider = ?, private_path = ?, snapshot_revision = ?,
                      last_refreshed_at = ?
                WHERE target_name = ?""",
            (provider, str(path), revision, now, name),
        )
    database.connection.commit()


def _execute_index(arguments: argparse.Namespace) -> dict[str, object]:
    from media_catalog.search_index.projection import (
        LOOKUP_FORMAT,
        read_snapshot,
        registered_targets,
    )

    catalog = arguments.catalog
    label = public_path(catalog)
    if arguments.index_command == "list":
        with CatalogDatabase(catalog) as database:
            targets = registered_targets(database.connection)
        return {
            "catalog": label,
            "count": len(targets),
            "indexes": [target.as_dict() for target in targets],
        }
    if arguments.index_command == "prune":
        provider = arguments.provider.strip()
        downloads = _default_downloads_dir(catalog, provider)
        with CatalogDatabase(catalog) as database:
            targets = registered_targets(database.connection)
        provider_targets = [t for t in targets if t.provider == provider]
        broken = [t for t in provider_targets if t.problem is not None]
        unanchored = [
            t.name
            for t in provider_targets
            if t.problem is None and t.snapshot is not None and not t.snapshot.artifact_path
        ]
        if arguments.apply and broken:
            # A broken registration cannot contribute its artifact
            # reference; pruning now could delete the artifact its
            # projection needs for a rebuild.
            raise ValueError(
                f"provider {provider} has broken registration(s)"
                f" ({', '.join(sorted(t.name for t in broken))});"
                " resolve them before pruning with --apply"
            )
        if arguments.apply and unanchored:
            # A projection that records no artifact path cannot protect its
            # rebuild source either; same stance as broken registrations.
            raise ValueError(
                f"provider {provider} has registration(s) without a recorded"
                f" artifact path ({', '.join(sorted(unanchored))});"
                " refusing to prune with --apply"
            )
        referenced: set[str] = set()
        for target in provider_targets:
            if target.snapshot is None:
                continue
            artifact_path = target.snapshot.artifact_path
            if artifact_path:
                referenced.add(Path(artifact_path).name)
        stale: list[dict[str, object]] = []
        skipped_recent: list[str] = []
        deleted: list[str] = []
        grace_seconds = 3600.0
        if downloads.is_dir():
            now = time.time()
            for entry in sorted(downloads.iterdir()):
                if not entry.is_file() or entry.name in referenced:
                    continue
                record: dict[str, object] = {"file": entry.name, "byte_size": entry.stat().st_size}
                if arguments.apply and now - entry.stat().st_mtime < grace_seconds:
                    # An import registers its artifact only after the build
                    # finishes; a fresh file may be in flight and must not
                    # be deleted from under it.
                    skipped_recent.append(entry.name)
                    record["skipped"] = "modified within the last hour (possible in-flight import)"
                    stale.append(record)
                    continue
                if arguments.apply:
                    entry.unlink()
                    deleted.append(entry.name)
                stale.append(record)
        return {
            "catalog": label,
            "provider": provider,
            "downloads_dir": public_path(downloads),
            "referenced": sorted(referenced),
            "prunable": stale,
            "deleted": deleted,
            "skipped_recent": skipped_recent,
            "applied": bool(arguments.apply),
        }
    if arguments.index_command == "register":
        provider = arguments.provider.strip()
        name = (arguments.name or provider).strip()
        path = arguments.path or _default_index_path(catalog, provider)
        snapshot = read_snapshot(path)  # raises on missing/wrong format
        if snapshot.provider != provider:
            raise ValueError(
                f"projection reports provider {snapshot.provider or '?'},"
                f" registration names {provider}"
            )
        if arguments.name is None and "verified_md5" not in snapshot.capabilities:
            # Registering a non-post projection under the default provider
            # name would silently rebind the posts target and drop its post
            # methods.  An explicit --name is the operator's confirmation.
            raise ValueError(
                f"this projection serves {', '.join(snapshot.capabilities)};"
                " register it with an explicit --name (e.g."
                f" --name {provider}-artists)"
            )
        with CatalogDatabase(catalog) as database:
            _upsert_registration(
                database, name=name, provider=provider, path=path, revision=snapshot.revision
            )
        return {
            "catalog": label,
            "target": name,
            "provider": provider,
            "format": LOOKUP_FORMAT,
            "snapshot_revision": snapshot.revision,
            "record_count": snapshot.record_count,
        }
    # import
    provider = arguments.provider
    if provider == "danbooru":
        if arguments.download:
            raise ValueError("danbooru imports require --artifact (no provider export listing)")
        if arguments.export != "posts":
            raise ValueError("--export is e621-only; danbooru imports are posts snapshots")
        from media_catalog.search_index.importers.danbooru_parquet import (
            import_danbooru_parquet,
        )

        destination = arguments.path or _default_index_path(catalog, provider)
        result = import_danbooru_parquet(
            arguments.artifact,
            destination=destination,
            checksum=arguments.checksum,
            max_records=arguments.max_records,
        )
        with CatalogDatabase(catalog) as database:
            _upsert_registration(
                database,
                name=provider,
                provider=provider,
                path=destination,
                revision=result.snapshot_revision,
            )
        return {
            "catalog": label,
            "target": provider,
            "export": "posts-parquet",
            **result.as_dict(),
        }
    if provider != "e621":  # pragma: no cover - argparse choices guard this
        raise ValueError(f"no importer for provider {provider}")
    export_name = arguments.export
    target_name = provider if export_name == "posts" else f"{provider}-artists"
    destination = arguments.path or (
        _default_index_path(catalog, provider)
        if export_name == "posts"
        else _default_index_path(catalog, target_name)
    )
    download_note: dict[str, object] | None = None
    artifact_path = arguments.artifact
    checksum = arguments.checksum
    if arguments.download:
        # Explicit network: listing request + streamed artifact download,
        # verified against the provider's published checksum.  An operator
        # --checksum is compared against the listing (pins intent) before
        # any transfer.  A matching existing artifact is reused, so
        # re-running is the refresh.
        from media_catalog.search_index.download import (
            download_e621_export,
            download_result_dict,
        )

        artifact_path, listing = download_e621_export(
            _default_downloads_dir(catalog, provider),
            export_name=export_name,
            expected_checksum=arguments.checksum,
        )
        checksum = listing.checksum
        download_note = download_result_dict(artifact_path, listing)
    if export_name == "artists":
        from media_catalog.search_index.importers.e621_artists_export import (
            import_e621_artists_export,
        )

        result = import_e621_artists_export(
            artifact_path,
            destination=destination,
            checksum=checksum,
            max_records=arguments.max_records,
        )
    else:
        from media_catalog.search_index.importers.e621_export import import_e621_export

        result = import_e621_export(
            artifact_path,
            destination=destination,
            checksum=checksum,
            max_records=arguments.max_records,
        )
    with CatalogDatabase(catalog) as database:
        _upsert_registration(
            database,
            name=target_name,
            provider=provider,
            path=destination,
            revision=result.snapshot_revision,
        )
    payload: dict[str, object] = {
        "catalog": label,
        "target": target_name,
        "export": export_name,
        **result.as_dict(),
    }
    if download_note is not None:
        payload["download"] = download_note
    return payload
