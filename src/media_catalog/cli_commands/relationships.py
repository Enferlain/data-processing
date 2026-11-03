"""Relationship review and materialization: relationships."""

from __future__ import annotations

import argparse
from pathlib import Path

from media_catalog.cli_commands.support import add_json, utc_now
from media_catalog.database import CatalogDatabase
from media_catalog.discovery.support import parse_match_ref
from media_catalog.output import public_path
from media_catalog.relationships import (
    get_relationship,
    list_relationships,
    materialize_candidates,
    review_relationship,
    seed_relationships,
)

COMMANDS = ("relationships",)


def register(commands: argparse._SubParsersAction) -> None:
    relationships = commands.add_parser("relationships")
    relationship_commands = relationships.add_subparsers(
        dest="relationships_command", required=True
    )
    relationship_materialize = relationship_commands.add_parser(
        "materialize", description="Turn confirmed post candidates into relationships"
    )
    relationship_materialize.add_argument("catalog", type=Path)
    relationship_materialize.add_argument(
        "--candidate", metavar="REF", help="materialize one candidate, e.g. post:7"
    )
    add_json(relationship_materialize)
    relationship_seed = relationship_commands.add_parser("seed")
    relationship_seed.add_argument("catalog", type=Path)
    add_json(relationship_seed)
    relationship_list = relationship_commands.add_parser("list")
    relationship_list.add_argument("catalog", type=Path)
    relationship_list.add_argument("--kind", dest="relation_kind")
    relationship_list.add_argument("--status", dest="epistemic_status")
    relationship_list.add_argument("--review-state", dest="review_state")
    relationship_list.add_argument("--limit", type=int, default=200)
    add_json(relationship_list)
    relationship_show = relationship_commands.add_parser("show")
    relationship_show.add_argument("catalog", type=Path)
    relationship_show.add_argument("--relationship-id", type=int, required=True)
    add_json(relationship_show)
    relationship_review = relationship_commands.add_parser("review")
    relationship_review.add_argument("catalog", type=Path)
    relationship_review.add_argument("--relationship-id", type=int, required=True)
    relationship_review.add_argument(
        "--decision", choices=("confirm", "reject", "pending"), required=True
    )
    relationship_review.add_argument("--note")
    add_json(relationship_review)


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    catalog_label = public_path(arguments.catalog)
    with CatalogDatabase(arguments.catalog) as database:
        if arguments.relationships_command == "materialize":
            candidate_id = None
            if arguments.candidate is not None:
                kind, candidate_id = parse_match_ref(arguments.candidate)
                if kind != "post":
                    raise ValueError("materialization accepts post candidates only")
            return {
                "catalog": catalog_label,
                **materialize_candidates(database, candidate_id=candidate_id, clock=utc_now),
            }
        if arguments.relationships_command == "seed":
            return {
                "catalog": catalog_label,
                **seed_relationships(database, clock=utc_now),
            }
        if arguments.relationships_command == "list":
            return {
                "catalog": catalog_label,
                "relationships": list_relationships(
                    database,
                    relation_kind=arguments.relation_kind,
                    epistemic_status=arguments.epistemic_status,
                    review_state=arguments.review_state,
                    limit=arguments.limit,
                ),
            }
        if arguments.relationships_command == "show":
            shown = get_relationship(database, arguments.relationship_id)
            if shown is None:
                raise ValueError(f"relationship {arguments.relationship_id} not found")
            return {"catalog": catalog_label, **shown}
        return {
            "catalog": catalog_label,
            **review_relationship(
                database,
                arguments.relationship_id,
                arguments.decision,
                note=arguments.note,
                clock=utc_now,
            ),
        }
