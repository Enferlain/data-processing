from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

POST_ID_PATTERN = re.compile(r"(?:status/|^)(\d{2,20})(?:\D|$)")
LIKE_FILE_PATTERN = re.compile(r"likes?(?:-part\d+)?\.js", re.IGNORECASE)


class ArchiveError(ValueError):
    """Raised when an X archive cannot be read or has an unexpected structure."""


@dataclass(frozen=True, slots=True)
class ArchivedLike:
    post_id: str
    post_url: str
    archived_text: str | None = None


def read_likes(source: Path) -> list[ArchivedLike]:
    """Read likes from an X archive ZIP, extracted archive, or like.js file."""
    likes: dict[str, ArchivedLike] = {}
    record_count = 0

    for text in _read_like_javascripts(source):
        payload = _parse_javascript_array(text)
        record_count += len(payload)
        for item in payload:
            if not isinstance(item, dict):
                continue
            like = item.get("like", item)
            if not isinstance(like, dict):
                continue

            url = _first_string(like, "expandedUrl", "expanded_url", "tweetUrl", "url")
            post_id = _first_string(like, "tweetId", "tweet_id", "postId", "id")
            if not post_id and url:
                match = POST_ID_PATTERN.search(url)
                post_id = match.group(1) if match else None
            if not post_id or not re.fullmatch(r"\d{2,20}", post_id):
                continue

            canonical_url = url or f"https://x.com/i/web/status/{post_id}"
            archived_text = _first_string(like, "fullText", "full_text", "text")
            if post_id in likes and archived_text is None:
                archived_text = likes[post_id].archived_text
            likes[post_id] = ArchivedLike(post_id, canonical_url, archived_text)

    if record_count and not likes:
        raise ArchiveError("The like file contained records, but no post IDs could be recognized")
    return list(likes.values())


def _read_like_javascripts(source: Path) -> list[str]:
    if source.is_dir():
        candidates = sorted(
            path
            for path in source.rglob("*.js")
            if path.parent.name == "data" and LIKE_FILE_PATTERN.fullmatch(path.name)
        )
        if candidates:
            return [candidate.read_text(encoding="utf-8-sig") for candidate in candidates]
        raise ArchiveError(f"Could not find data/like.js in extracted archive: {source}")

    if not source.is_file():
        raise ArchiveError(f"Archive source does not exist: {source}")

    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            members = _find_zip_members(archive.namelist())
            if not members:
                raise ArchiveError(f"Could not find data/like.js in archive: {source}")
            return [archive.read(member).decode("utf-8-sig") for member in members]

    return [source.read_text(encoding="utf-8-sig")]


def _find_zip_members(names: list[str]) -> list[str]:
    members = []
    for original in names:
        path = original.replace("\\", "/").lstrip("./")
        parts = path.split("/")
        if len(parts) >= 2 and parts[-2] == "data" and LIKE_FILE_PATTERN.fullmatch(parts[-1]):
            members.append(original)
    return sorted(members)


def _parse_javascript_array(text: str) -> list[object]:
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        raise ArchiveError("The like file did not contain a JSON array")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise ArchiveError(
            f"The like file is not valid JSON-wrapped JavaScript: {error}"
        ) from error
    if not isinstance(payload, list):
        raise ArchiveError("The like file payload was not a list")
    return payload


def _first_string(data: dict[object, object], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None
