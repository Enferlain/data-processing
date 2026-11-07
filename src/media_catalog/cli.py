"""Command-line entry point: parsing, rendering, and exit-code policy."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from media_catalog.cli_commands import FAMILIES
from media_catalog.credentials import load_credentials
from media_catalog.output import bounded_error, render_result
from media_catalog.storage.cas import AssetStorageError


def _family_commands(family) -> tuple[str, ...]:
    """The top-level command names a family module registers."""
    return tuple(getattr(family, "COMMANDS", ()))


_FAMILY_BY_COMMAND = {
    command: family for family in FAMILIES for command in _family_commands(family)
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catalog", description="Local cross-platform media catalog"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for family in FAMILIES:
        family.register(commands)
    return parser


def _run(arguments: argparse.Namespace) -> dict[str, object]:
    family = _FAMILY_BY_COMMAND[arguments.command]
    return family.execute(arguments)


def main(argv: list[str] | None = None) -> None:
    arguments = build_parser().parse_args(argv)
    as_json = getattr(arguments, "json", False)
    try:
        load_credentials()
        result = _run(arguments)
    except (AssetStorageError, OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        private_paths = tuple(
            value
            for name in ("source", "catalog", "source_root", "media_root")
            if isinstance((value := getattr(arguments, name, None)), Path)
        )
        message = bounded_error(error, private_paths=private_paths)
        if as_json:
            raise SystemExit(json.dumps({"error": message}, ensure_ascii=False)) from error
        raise SystemExit(f"error: {message}") from error
    if arguments.command == "adapter-doctor" and not as_json:
        pass  # the doctor rendered its own human report inside its family
    else:
        print(render_result(result, as_json=as_json))
    if (
        arguments.command == "assets"
        and arguments.asset_command not in {"download-plan", "download-runs", "download-run-show"}
        and result.get("status") in {"partial", "failed", "issues"}
    ):
        raise SystemExit(2)
    if (
        arguments.command == "fetch"
        and not arguments.resolve_only
        and result.get("status") in {"paused", "failed"}
    ):
        raise SystemExit(2)
    if (
        arguments.command == "metadata"
        and arguments.metadata_command not in {"runs", "run-show"}
        and result.get("status") in {"paused", "failed"}
    ):
        raise SystemExit(2)
    if arguments.command == "adapter-doctor" and result.get("status") == "failed":
        raise SystemExit(2)
    if (
        arguments.command == "library"
        and arguments.library_command in {"run", "resume"}
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
