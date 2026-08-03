from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

from x_likes.archive import ArchiveError, read_likes
from x_likes.database import LikesDatabase
from x_likes.media import download_image
from x_likes.provider import FxTwitterClient, ProviderError, ProviderUnavailable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="x-likes",
        description="Archive liked posts from an exported X account archive.",
    )
    parser.add_argument("archive", type=Path, help="X archive ZIP, extracted directory, or like.js")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("x-likes-output"),
        help="Output directory (default: x-likes-output)",
    )
    parser.add_argument(
        "--download-images",
        action="store_true",
        help="Download images after importing and enriching post metadata",
    )
    parser.add_argument(
        "--import-only",
        action="store_true",
        help="Import archive data without making network requests",
    )
    parser.add_argument("--refresh", action="store_true", help="Refetch already enriched posts")
    parser.add_argument("--limit", type=_positive_int, help="Fetch at most this many posts")
    parser.add_argument(
        "--delay",
        type=_nonnegative_float,
        default=0.5,
        help="Seconds between metadata requests (default: 0.5)",
    )
    parser.add_argument(
        "--provider-base-url",
        default="https://api.fxtwitter.com",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    arguments = build_parser().parse_args(argv)
    if arguments.import_only and arguments.download_images:
        raise SystemExit("error: --download-images cannot be combined with --import-only")
    try:
        likes = read_likes(arguments.archive)
    except ArchiveError as error:
        raise SystemExit(f"error: {error}") from error

    arguments.output.mkdir(parents=True, exist_ok=True)
    database_path = arguments.output / "likes.sqlite3"
    with LikesDatabase(database_path) as database:
        database.import_likes(likes)
        print(f"Imported {len(likes)} unique likes into {database_path}")

        if not arguments.import_only:
            _fetch_metadata(database, arguments)
            if arguments.download_images:
                _download_images(database, arguments.output / "media")

        summary = database.summary()
        print(
            "Summary: "
            f"{summary['posts']} posts, {summary['accounts']} accounts, "
            f"{summary['fetched']} enriched, "
            f"{summary['unavailable']} unavailable, {summary['fetch_errors']} fetch errors, "
            f"{summary['images']} images, "
            f"{summary['downloaded']} downloaded"
        )


def _fetch_metadata(database: LikesDatabase, arguments: argparse.Namespace) -> None:
    post_ids = database.posts_to_fetch(refresh=arguments.refresh, limit=arguments.limit)
    if not post_ids:
        print("No posts need metadata enrichment")
        return

    with FxTwitterClient(base_url=arguments.provider_base_url) as provider:
        for number, post_id in enumerate(post_ids, start=1):
            try:
                metadata = provider.fetch(post_id)
                database.save_metadata(metadata, provider="fxtwitter")
                print(f"[{number}/{len(post_ids)}] Enriched {post_id}")
            except ProviderError as error:
                unavailable = isinstance(error, ProviderUnavailable)
                database.save_fetch_error(
                    post_id,
                    str(error),
                    status="unavailable" if unavailable else "error",
                    unavailable_reason=error.reason if unavailable else None,
                    raw=error.raw,
                )
                print(
                    f"[{number}/{len(post_ids)}] Could not enrich {post_id}: {error}",
                    file=sys.stderr,
                )
            if number < len(post_ids) and arguments.delay:
                time.sleep(arguments.delay)


def _download_images(database: LikesDatabase, media_root: Path) -> None:
    images = database.pending_images()
    if not images:
        print("No images need downloading")
        return

    with httpx.Client(
        follow_redirects=True,
        timeout=60,
        headers={"User-Agent": "x-likes-archiver/0.1 (personal archive)"},
    ) as client:
        for number, image in enumerate(images, start=1):
            try:
                result = download_image(image, output_root=media_root, client=client)
                relative_path = result.local_path.relative_to(media_root.parent)
                database.save_download(
                    image,
                    local_path=str(relative_path),
                    file_size=result.file_size,
                    md5=result.md5,
                    sha256=result.sha256,
                    phash=result.phash,
                )
                print(f"[{number}/{len(images)}] Downloaded {relative_path}")
            except (httpx.HTTPError, OSError, ValueError) as error:
                database.save_download_error(image, str(error))
                print(
                    f"[{number}/{len(images)}] Could not download image "
                    f"for {image.post_id}: {error}",
                    file=sys.stderr,
                )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed
