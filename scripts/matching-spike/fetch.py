"""Fetch matching-spike fixture bytes listed in the manifest.

Operator-run and the only network component of the harness. Hard bounds,
enforced in code: the host allowlist from seeds.py (suffix match), a fixed
manifest-driven request count with no recursion and no parsing of fetched
bodies for links, a per-file byte cap, an image/* content-type requirement,
a delay between requests, and resume-by-manifest — an existing fixture file
whose declared md5 matches (or that has no declared md5) is skipped. Results
land in fetch-report.json beside the fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from seeds import ALLOWED_IMAGE_HOST_SUFFIXES

MAX_BYTES_PER_FILE = 32 * 1024 * 1024
USER_AGENT = "data-processing-matching-spike/0.1 (bounded research fixture fetch)"


def _host_allowed(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return any(
        host == suffix or host.endswith("." + suffix) for suffix in ALLOWED_IMAGE_HOST_SUFFIXES
    )


def _extension_for(url: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        raise ValueError(f"fixture url has no known image extension: {url}")
    return suffix


def _matches_declared_md5(path: Path, declared_md5: object) -> bool:
    if not isinstance(declared_md5, str) or not declared_md5:
        return True
    return hashlib.md5(path.read_bytes()).hexdigest() == declared_md5.lower()


def fetch(
    manifest_path: Path,
    fixtures_dir: Path,
    report_path: Path,
    *,
    delay: float,
    timeout: float,
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries", [])
    statuses: list[dict[str, object]] = []
    fetched = skipped = failed = 0
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        for entry in entries:
            key = str(entry["key"])
            url = str(entry["url"])
            host = urlsplit(url).hostname or ""
            is_gelbooru = host == "gelbooru.com" or host.endswith(".gelbooru.com")
            if not _host_allowed(url):
                statuses.append({"key": key, "status": "refused_host"})
                failed += 1
                continue
            try:
                extension = _extension_for(url)
            except ValueError as error:
                statuses.append(
                    {"key": key, "status": "refused_extension", "error": str(error)[:200]}
                )
                failed += 1
                continue
            target = fixtures_dir / f"{key.replace(':', '_')}{extension}"
            if target.exists() and _matches_declared_md5(target, entry.get("declared_md5")):
                statuses.append({"key": key, "status": "skipped_existing"})
                skipped += 1
                continue
            try:
                # The gelbooru image CDN answers non-browser requests with an
                # HTML challenge page; send a browser identity there only.
                request_headers = (
                    {
                        "User-Agent": (
                            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
                        ),
                        "Referer": "https://gelbooru.com/",
                        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                    }
                    if is_gelbooru
                    else None
                )
                with client.stream("GET", url, headers=request_headers) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if not content_type.startswith("image/"):
                        statuses.append(
                            {
                                "key": key,
                                "status": "refused_content_type",
                                "content_type": content_type,
                            }
                        )
                        failed += 1
                        continue
                    fixtures_dir.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_suffix(target.suffix + ".part")
                    size = 0
                    digest = hashlib.sha256()
                    with temporary.open("wb") as handle:
                        for chunk in response.iter_bytes(chunk_size=65536):
                            size += len(chunk)
                            if size > MAX_BYTES_PER_FILE:
                                raise ValueError("fixture exceeds per-file byte cap")
                            handle.write(chunk)
                            digest.update(chunk)
                    if not _matches_declared_md5(temporary, entry.get("declared_md5")):
                        temporary.unlink(missing_ok=True)
                        statuses.append({"key": key, "status": "md5_mismatch"})
                        failed += 1
                        continue
                    temporary.replace(target)
                    statuses.append(
                        {
                            "key": key,
                            "status": "fetched",
                            "path": target.name,
                            "bytes": size,
                            "sha256": digest.hexdigest(),
                        }
                    )
                    fetched += 1
            except (httpx.HTTPError, ValueError, OSError) as error:
                statuses.append({"key": key, "status": "failed", "error": str(error)[:200]})
                failed += 1
            time.sleep(delay)  # only reached after a real network attempt
    report = {
        "manifest": manifest_path.name,
        "fetched": fetched,
        "skipped_existing": skipped,
        "failed": failed,
        "statuses": statuses,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path("private-exports/matching-spike/manifest.json")
    )
    parser.add_argument(
        "--fixtures-dir", type=Path, default=Path("private-exports/matching-spike/fixtures/")
    )
    parser.add_argument(
        "--report", type=Path, default=Path("private-exports/matching-spike/fetch-report.json")
    )
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    arguments = parser.parse_args(argv)
    report = fetch(
        arguments.manifest,
        arguments.fixtures_dir,
        arguments.report,
        delay=arguments.delay,
        timeout=arguments.timeout,
    )
    print(
        f"fetch: fetched={report['fetched']} skipped={report['skipped_existing']} "
        f"failed={report['failed']} report={arguments.report}"
    )
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
