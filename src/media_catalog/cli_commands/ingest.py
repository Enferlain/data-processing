"""Source importers and link/candidate review: ingest, discover-links, links,
matches, match-show, match-review."""

from __future__ import annotations

import argparse
from pathlib import Path

from media_catalog.cli_commands.support import add_json
from media_catalog.database import CatalogDatabase
from media_catalog.discovery import DiscoveryService
from media_catalog.imports.x_likes_db import import_x_likes_database
from media_catalog.imports.xarchive import import_xarchive
from media_catalog.output import public_path

COMMANDS = ("ingest", "discover-links", "links", "matches", "match-show", "match-review")


def register(commands: argparse._SubParsersAction) -> None:
    ingest = commands.add_parser("ingest")
    sources = ingest.add_subparsers(dest="source_kind", required=True)
    for source_kind in ("x-likes-db", "xarchive"):
        source = sources.add_parser(source_kind)
        source.add_argument("source", type=Path)
        source.add_argument("--catalog", type=Path, required=True)
        add_json(source)
    discover = commands.add_parser("discover-links")
    discover.add_argument("catalog", type=Path)
    add_json(discover)
    links = commands.add_parser("links")
    links.add_argument("catalog", type=Path)
    links.add_argument("--subject-kind", choices=("account", "attribution", "post"))
    links.add_argument("--subject-id", type=int)
    links.add_argument("--source-context")
    links.add_argument("--platform")
    links.add_argument("--instance")
    links.add_argument("--object-kind", choices=("account", "post", "artist", "media_asset"))
    links.add_argument(
        "--state", choices=("recognized", "unresolved", "invalid", "redirect_required")
    )
    add_json(links)
    matches = commands.add_parser("matches")
    matches.add_argument("catalog", type=Path)
    matches.add_argument("--kind", choices=("account", "attribution", "post"))
    matches.add_argument("--state", choices=("pending", "confirmed", "rejected"))
    add_json(matches)
    show = commands.add_parser("match-show")
    show.add_argument("catalog", type=Path)
    show.add_argument("match_ref")
    add_json(show)
    review = commands.add_parser("match-review")
    review.add_argument("catalog", type=Path)
    review.add_argument("match_ref")
    review.add_argument("--decision", choices=("confirm", "reject", "pending"), required=True)
    review.add_argument("--note")
    review.add_argument("--expected-generation", type=int)
    review.add_argument("--expected-revision", type=int)
    add_json(review)


def execute(arguments: argparse.Namespace) -> dict[str, object]:
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
