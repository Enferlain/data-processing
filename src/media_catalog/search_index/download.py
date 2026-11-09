"""Explicit provider-artifact download for index imports (bead an1).

`catalog index import --download` fetches the e621 daily DB export itself:
one request to the public listing endpoint, one streamed artifact download,
SHA-256 verified against the listing before the import ever reads it.  The
artifact lands in the provider's downloads directory and is retained
untouched — the projection stays the rebuildable derived copy.  A matching
existing file is reused, so re-running the command is the e621 refresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from media_catalog.adapters.e621.config import E621_USER_AGENT
from media_catalog.search_index.importers.e621_export import sha256_file

E621_EXPORTS_URL = "https://e621.net/db_exports.json"
DOWNLOAD_TIMEOUT_SECONDS = 600.0


class ExportDownloadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExportListing:
    name: str
    file_name: str
    file_size: int
    checksum: str
    updated_at: str
    url: str


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": E621_USER_AGENT},
        follow_redirects=True,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )


def list_e621_exports(client: httpx.Client | None = None) -> dict[str, ExportListing]:
    """The current export listing, keyed by export name."""
    owns = client is None
    client = client or _client()
    try:
        response = client.get(E621_EXPORTS_URL)
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns:
            client.close()
    listings: dict[str, ExportListing] = {}
    if not isinstance(payload, list):
        raise ExportDownloadError("export listing is not a JSON array")
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        file_name = entry.get("file_name")
        checksum = entry.get("checksum")
        url = entry.get("url")
        if not all(isinstance(value, str) and value for value in (name, file_name, checksum, url)):
            continue
        if len(checksum) != 64:
            continue
        listings[name] = ExportListing(
            name=name,
            file_name=file_name,
            file_size=int(entry.get("file_size") or 0),
            checksum=checksum.lower(),
            updated_at=str(entry.get("updated_at") or ""),
            url=url,
        )
    if not listings:
        raise ExportDownloadError("export listing is empty or has no usable entries")
    return listings


def download_e621_export(
    destination_dir: Path,
    *,
    export_name: str = "posts",
    client: httpx.Client | None = None,
) -> tuple[Path, ExportListing]:
    """Fetch (or reuse) one export artifact, checksum-verified.

    Returns the artifact path and its listing entry.  An existing file whose
    digest matches the listing is reused without a second download.
    """
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    listing = list_e621_exports(client)
    if export_name not in listing:
        raise ExportDownloadError(
            f"export {export_name!r} is not in the listing"
            f" (available: {', '.join(sorted(listing))})"
        )
    entry = listing[export_name]
    artifact = destination_dir / entry.file_name
    if artifact.is_file() and sha256_file(artifact) == entry.checksum:
        return artifact, entry
    temp = artifact.with_name(artifact.name + ".part")
    if temp.exists():
        temp.unlink()
    owns = client is None
    client = client or _client()
    try:
        with client.stream("GET", entry.url) as response:
            response.raise_for_status()
            with temp.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    handle.write(chunk)
        actual = sha256_file(temp)
        if actual != entry.checksum:
            temp.unlink()
            raise ExportDownloadError(
                f"downloaded {entry.file_name} checksum mismatch:"
                f" listing {entry.checksum[:16]}…, computed {actual[:16]}…"
            )
        from os import replace

        replace(temp, artifact)
    finally:
        if owns:
            client.close()
    return artifact, entry


def download_result_dict(artifact: Path, entry: ExportListing) -> dict[str, Any]:
    return {
        "downloaded": artifact.name,
        "export": entry.name,
        "checksum": entry.checksum,
        "updated_at": entry.updated_at,
        "byte_size": artifact.stat().st_size,
    }
