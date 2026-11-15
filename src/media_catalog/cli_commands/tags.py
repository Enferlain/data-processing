"""`catalog tag`: operator labels — free-form local facts on catalog subjects.

Distinct from provider-observed tags (never touched) and from `catalog label`
(the interactive pair-calibration server)."""

from __future__ import annotations

import argparse
from pathlib import Path

from media_catalog.cli_commands.support import add_json
from media_catalog.database import CatalogDatabase
from media_catalog.operator_labels import (
    SUBJECT_KINDS,
    apply_label,
    create_label,
    current_labels,
    list_labels,
    retire_label,
    revoke_label,
    search_label,
)

COMMANDS = ("tag",)

_SUBJECT_FLAGS = {
    "file_seed": "--file-seed",
    "post": "--post",
    "asset": "--asset",
    "work": "--work",
}


def _subject_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    for kind in SUBJECT_KINDS:
        group.add_argument(_SUBJECT_FLAGS[kind], type=int, help=f"{kind} id")


def _selected_subject(arguments: argparse.Namespace) -> tuple[str, int]:
    for kind in SUBJECT_KINDS:
        value = getattr(arguments, kind)
        if value is not None:
            return kind, value
    raise ValueError("no subject selected")


def register(commands: argparse._SubParsersAction) -> None:
    parser = commands.add_parser(
        "tag",
        description=(
            "Operator labels: free-form local labels on catalog subjects"
            " (file seeds, posts, assets, works). Labels are yours — never"
            " provider tags — and a label covers identical content across"
            " platforms. Add/remove labels freely; history is kept."
        ),
    )
    tag_commands = parser.add_subparsers(dest="tag_command", required=True)

    create = tag_commands.add_parser("create", description="Create an operator label")
    create.add_argument("catalog", type=Path)
    create.add_argument("name")
    create.add_argument("--description")
    add_json(create)

    listing = tag_commands.add_parser("list", description="List labels with counts")
    listing.add_argument("catalog", type=Path)
    add_json(listing)

    remove = tag_commands.add_parser(
        "remove", description="Retire a label (history kept, no new applications)"
    )
    remove.add_argument("catalog", type=Path)
    remove.add_argument("name")
    add_json(remove)

    apply_cmd = tag_commands.add_parser("apply", description="Apply a label to a subject")
    apply_cmd.add_argument("catalog", type=Path)
    apply_cmd.add_argument("name")
    _subject_arguments(apply_cmd)
    apply_cmd.add_argument("--by", default="operator", help="operator attribution")
    apply_cmd.add_argument("--note")
    add_json(apply_cmd)

    revoke = tag_commands.add_parser("revoke", description="Revoke a label from a subject")
    revoke.add_argument("catalog", type=Path)
    revoke.add_argument("name")
    _subject_arguments(revoke)
    revoke.add_argument("--by", default="operator", help="operator attribution")
    revoke.add_argument("--note")
    add_json(revoke)

    show = tag_commands.add_parser(
        "show", description="Labels on a subject, including identical-content inheritance"
    )
    show.add_argument("catalog", type=Path)
    _subject_arguments(show)
    add_json(show)

    search = tag_commands.add_parser("search", description="Subjects carrying a label")
    search.add_argument("catalog", type=Path)
    search.add_argument("name")
    search.add_argument("--limit", type=int, default=200)
    add_json(search)


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    command = arguments.tag_command
    with CatalogDatabase(arguments.catalog) as database:
        connection = database.connection
        if command == "create":
            return create_label(connection, arguments.name, description=arguments.description)
        if command == "list":
            return {"labels": list_labels(connection)}
        if command == "remove":
            return retire_label(connection, arguments.name)
        if command in ("apply", "revoke"):
            kind, subject_id = _selected_subject(arguments)
            record = (apply_label if command == "apply" else revoke_label)(
                connection,
                arguments.name,
                kind,
                subject_id,
                by=arguments.by,
                note=arguments.note,
            )
            return record
        if command == "show":
            kind, subject_id = _selected_subject(arguments)
            return current_labels(connection, kind, subject_id)
        if command == "search":
            return search_label(connection, arguments.name, limit=arguments.limit)
    raise ValueError(f"unknown tag command {command!r}")
