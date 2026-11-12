"""Command families for the catalog CLI.

Each family module exposes ``register(commands)`` (parser fragment) and
``execute(arguments)`` (dispatch handler); ``media_catalog.cli`` owns
registration order, argument parsing, rendering, and exit-code policy.
"""

from __future__ import annotations

from media_catalog.cli_commands import (
    admin,
    crosscheck,
    discovery,
    export,
    ingest,
    library,
    lookup,
    maintenance,
    media,
    metadata,
    relationships,
)

# Registration order is the help-output order; keep it stable.
FAMILIES = (
    admin,
    discovery,
    ingest,
    media,
    metadata,
    lookup,
    crosscheck,
    export,
    relationships,
    maintenance,
    library,
)

__all__ = [
    "FAMILIES",
    "admin",
    "crosscheck",
    "discovery",
    "export",
    "ingest",
    "library",
    "lookup",
    "maintenance",
    "media",
    "metadata",
    "relationships",
]
