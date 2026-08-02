from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
import imagehash
from PIL import Image

from x_likes.database import PendingImage

SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9_-]+")
ALLOWED_IMAGE_HOSTS = {"pbs.twimg.com"}
MAX_IMAGE_BYTES = 100 * 1024 * 1024
CONTENT_TYPE_EXTENSIONS = {
    "image/avif": ".avif",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@dataclass(frozen=True, slots=True)
class DownloadResult:
    local_path: Path
    file_size: int
    md5: str
    sha256: str
    phash: str


def download_image(
    image: PendingImage,
    *,
    output_root: Path,
    client: httpx.Client,
) -> DownloadResult:
    parsed_url = urlparse(image.source_url)
    if parsed_url.scheme != "https" or parsed_url.hostname not in ALLOWED_IMAGE_HOSTS:
        raise ValueError(f"Refusing unexpected image host: {parsed_url.hostname or 'missing'}")

    handle = SAFE_COMPONENT.sub("_", image.author_handle or "unknown").strip("_") or "unknown"
    directory = output_root / handle
    directory.mkdir(parents=True, exist_ok=True)

    with client.stream("GET", image.source_url) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").partition(";")[0].lower()
        if content_type not in CONTENT_TYPE_EXTENSIONS:
            raise ValueError(f"Expected an image response, received {content_type or 'unknown'}")
        content_length = response.headers.get("Content-Length")
        if content_length and content_length.isdigit() and int(content_length) > MAX_IMAGE_BYTES:
            raise ValueError(f"Image exceeds the {MAX_IMAGE_BYTES}-byte size limit")
        extension = _extension(image.source_url, content_type)
        destination = directory / f"{image.post_id}_{image.media_index:02d}{extension}"
        temporary = destination.with_suffix(destination.suffix + ".part")
        md5 = hashlib.md5(usedforsecurity=False)
        sha256 = hashlib.sha256()
        size = 0
        try:
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise ValueError(f"Image exceeds the {MAX_IMAGE_BYTES}-byte size limit")
                    output.write(chunk)
                    md5.update(chunk)
                    sha256.update(chunk)
            temporary.replace(destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    try:
        with Image.open(destination) as opened:
            perceptual_hash = str(imagehash.phash(opened))
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return DownloadResult(destination, size, md5.hexdigest(), sha256.hexdigest(), perceptual_hash)


def _extension(url: str, content_type: str) -> str:
    if content_type in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[content_type]
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in set(CONTENT_TYPE_EXTENSIONS.values()) else ".img"
