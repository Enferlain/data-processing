"""Build the matching-spike fixture manifest from local, retained data.

Merges three sources, all bounded and deterministic:

- the bookmark catalog (opened read-only): X media URLs sampled for
  orig/small variant pairs plus same-author and cross-author negative pairs;
- retained gelbooru DAPI captures (private-exports/gelbooru-captures): the
  test_list posts' provider-labeled file/sample/preview URLs with declared
  md5, dimensions, and creation time;
- FxTwitter (optional, three requests, the same service x-likes uses): media
  URLs for the three test_list X statuses, so cross-provider same-work pairs
  exist.

Same-media-ID reposts are byte-identical by construction (one URL serves any
number of posts), so they are not a measurable pair class; exact-byte
evidence instead comes from sha256 collisions among fetched fixtures, which
measure.py reports.

Writes private-exports/matching-spike/manifest.json with explicit entry and
pair lists; fetch.py and measure.py only consume the manifest. Nothing here
recurses, follows links, or exceeds the fixture cap in seeds.MAX_FIXTURE_FILES.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

import httpx
from seeds import (
    GELBOORU_GROUP3_PAIR_CLASS,
    MAX_FIXTURE_FILES,
    TEST_LIST_GROUPS,
    X_SAMPLING,
)

X_MEDIA_PATTERN = re.compile(r"^https://pbs\.twimg\.com/media/([A-Za-z0-9_-]+)\.(jpg|png|webp)")


def _connect(catalog: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)


def _x_media(catalog: Path) -> list[tuple[str, str, int]]:
    """Return (media_id, extension, post_id) for stored X media, stable order."""

    connection = _connect(catalog)
    try:
        rows = connection.execute(
            """SELECT m.remote_url, p.post_id
                 FROM media_occurrences m JOIN posts p ON p.post_id = m.post_id
                WHERE m.remote_url LIKE 'https://pbs.twimg.com/media/%'"""
        ).fetchall()
    finally:
        connection.close()
    media: dict[str, tuple[str, int]] = {}
    for url, post_id in rows:
        match = X_MEDIA_PATTERN.match(url)
        if match is not None:
            media.setdefault(match.group(1), (match.group(2), post_id))
    return [(media_id, ext, post_id) for media_id, (ext, post_id) in sorted(media.items())]


def _author_by_post(catalog: Path, post_ids: list[int]) -> dict[int, int]:
    connection = _connect(catalog)
    try:
        placeholders = ",".join("?" for _ in post_ids)
        rows = connection.execute(
            f"""SELECT post_id, account_id FROM post_participants
                 WHERE role = 'author' AND post_id IN ({placeholders})""",
            post_ids,
        ).fetchall()
    finally:
        connection.close()
    return dict(rows)


def _x_url(media_id: str, extension: str, variant: str) -> str:
    return f"https://pbs.twimg.com/media/{media_id}.{extension}?format={extension}&name={variant}"


def _entry(
    key: str,
    url: str,
    provider: str,
    variant: str,
    group: str | None,
    declared: dict[str, object] | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "key": key,
        "url": url,
        "provider": provider,
        "variant": variant,
        "group": group,
    }
    if declared:
        entry.update(declared)
    return entry


def _gelbooru_entries(captures_dir: Path) -> dict[int, list[dict[str, object]]]:
    """Return file/sample/preview entries per gelbooru post id."""

    by_post: dict[int, list[dict[str, object]]] = {}
    for capture in sorted(captures_dir.glob("*.dapi.json")):
        payload = json.loads(capture.read_text(encoding="utf-8"))
        posts = payload.get("post") if isinstance(payload, dict) else None
        if not isinstance(posts, list) or not posts:
            continue
        post = posts[0]
        post_id = int(post["id"])
        file_md5 = post.get("md5")
        dimensions = {
            "declared_width": post.get("width"),
            "declared_height": post.get("height"),
            "declared_created_at": post.get("created_at"),
        }
        entries = []
        for variant, field in (
            ("file", "file_url"),
            ("sample", "sample_url"),
            ("preview", "preview_url"),
        ):
            url = post.get(field)
            if isinstance(url, str) and url:
                # Only the file variant is covered by the post's declared
                # md5; provider-recompressed variants must not be gated on it.
                declared = dict(dimensions)
                if variant == "file":
                    declared["declared_md5"] = file_md5
                entries.append(
                    _entry(
                        f"gelbooru:{post_id}:{variant}",
                        url,
                        "gelbooru",
                        variant,
                        None,
                        declared,
                    )
                )
        by_post[post_id] = entries
    return by_post


def _fxtwitter_media(status_id: str, client: httpx.Client) -> list[tuple[str, str]]:
    """Return (media_id, extension) for one status; empty on any failure."""

    try:
        response = client.get(f"https://api.fxtwitter.com/status/{status_id}")
        response.raise_for_status()
        photos = response.json().get("tweet", {}).get("media", {}).get("photos", [])
    except (httpx.HTTPError, ValueError) as error:
        print(f"warning: fxtwitter resolution failed for {status_id}: {error}", file=sys.stderr)
        return []
    results = []
    for photo in photos:
        match = X_MEDIA_PATTERN.match(str(photo.get("url", "")))
        if match is not None:
            results.append((match.group(1), match.group(2)))
    return results


def _group_pairs(
    group_name: str,
    x_keys: list[str],
    gelbooru_file_keys: list[str],
) -> list[dict[str, str]]:
    pairs = [
        {"a": first, "b": second, "class": "x_variant", "group": group_name}
        for index, first in enumerate(x_keys)
        for second in x_keys[index + 1 :]
    ]
    pairs.extend(
        {
            "a": x_key,
            "b": gelbooru_key,
            "class": "cross_provider_same_work",
            "group": group_name,
        }
        for x_key in x_keys
        for gelbooru_key in gelbooru_file_keys
    )
    if group_name == "g3" and len(gelbooru_file_keys) == 3:
        pairs.extend(
            {"a": first, "b": second, "class": GELBOORU_GROUP3_PAIR_CLASS, "group": group_name}
            for first, second in (
                (gelbooru_file_keys[0], gelbooru_file_keys[1]),
                (gelbooru_file_keys[0], gelbooru_file_keys[2]),
                (gelbooru_file_keys[1], gelbooru_file_keys[2]),
            )
        )
    return pairs


def build_manifest(
    catalog: Path,
    captures_dir: Path,
    output: Path,
    *,
    use_fxtwitter: bool,
) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    pairs: list[dict[str, str]] = []
    rng = random.Random(X_SAMPLING["rng_seed"])

    gelbooru_by_post = _gelbooru_entries(captures_dir)

    with httpx.Client(
        timeout=15.0,
        headers={
            "User-Agent": "x-likes-archiver/0.1 (personal archive)",
            "Accept": "application/json",
        },
    ) as client:
        for group in TEST_LIST_GROUPS:
            group_name = str(group["group"])
            x_keys: list[str] = []
            if use_fxtwitter:
                for media_id, extension in _fxtwitter_media(str(group["x_status_id"]), client):
                    for variant in ("orig", "small"):
                        key = f"x:{media_id}:{variant}"
                        x_keys.append(key)
                        entries.append(
                            _entry(
                                key,
                                _x_url(media_id, extension, variant),
                                "x",
                                variant,
                                group_name,
                            )
                        )
            group_post_ids = group["gelbooru_post_ids"]
            assert isinstance(group_post_ids, list)
            file_keys: list[str] = []
            for post_id in group_post_ids:
                post_keys: list[str] = []
                for entry in gelbooru_by_post.get(post_id, []):
                    entry["group"] = group_name
                    post_keys.append(str(entry["key"]))
                    entries.append(entry)
                post_file_keys = [key for key in post_keys if key.endswith(":file")]
                file_keys.extend(post_file_keys)
                # Same-post provider-labeled variants only: another post's
                # sample is not a re-encode of this post's file.
                for post_file_key in post_file_keys:
                    for other in post_keys:
                        if other == post_file_key:
                            continue
                        pair_class = (
                            "gelbooru_sample" if other.endswith(":sample") else "gelbooru_preview"
                        )
                        pairs.append(
                            {
                                "a": post_file_key,
                                "b": other,
                                "class": pair_class,
                                "group": group_name,
                            }
                        )
            pairs.extend(_group_pairs(group_name, x_keys, file_keys))

    media_rows = _x_media(catalog)
    media_index = {media_id: (ext, post_id) for media_id, ext, post_id in media_rows}
    author_by_post = _author_by_post(catalog, [post_id for _, _, post_id in media_rows])

    variant_target = int(X_SAMPLING["variant_media_target"])
    variant_ids = [media_id for media_id, _, _ in media_rows]
    stride = max(1, len(variant_ids) // variant_target) if variant_ids else 1
    sampled = variant_ids[::stride][:variant_target]

    truncated = False
    budget = MAX_FIXTURE_FILES - len(entries)
    if len(sampled) * 2 > budget:
        sampled = sampled[: max(0, budget // 2)]
        truncated = True
    for media_id in sampled:
        extension = media_index[media_id][0]
        for variant in ("orig", "small"):
            entries.append(
                _entry(
                    f"x:{media_id}:{variant}",
                    _x_url(media_id, extension, variant),
                    "x",
                    variant,
                    None,
                )
            )
        pairs.append(
            {
                "a": f"x:{media_id}:orig",
                "b": f"x:{media_id}:small",
                "class": "x_variant",
                "group": "x_sample",
            }
        )

    sampled_with_author = [
        (media_id, author_by_post.get(media_index[media_id][1])) for media_id in sampled
    ]
    by_author: dict[int, list[str]] = {}
    for media_id, author in sampled_with_author:
        if author is not None:
            by_author.setdefault(author, []).append(media_id)
    same_author_candidates = [
        (first, second)
        for ids in by_author.values()
        for index, first in enumerate(ids)
        for second in ids[index + 1 :]
    ]
    rng.shuffle(same_author_candidates)
    for first, second in same_author_candidates[: int(X_SAMPLING["same_artist_pairs"])]:
        pairs.append(
            {
                "a": f"x:{first}:orig",
                "b": f"x:{second}:orig",
                "class": "same_artist_near_negative",
                "group": "negatives",
            }
        )

    cross_pairs_pool = [
        (first, second)
        for index, (first, first_author) in enumerate(sampled_with_author)
        for second, second_author in sampled_with_author[index + 1 :]
        if first_author != second_author
    ]
    rng.shuffle(cross_pairs_pool)
    for first, second in cross_pairs_pool[: int(X_SAMPLING["cross_artist_pairs"])]:
        pairs.append(
            {
                "a": f"x:{first}:orig",
                "b": f"x:{second}:orig",
                "class": "cross_artist_negative",
                "group": "negatives",
            }
        )

    class_counts: dict[str, int] = {}
    for pair in pairs:
        class_counts[pair["class"]] = class_counts.get(pair["class"], 0) + 1

    manifest = {
        "catalog": catalog.name,
        "captures": captures_dir.name,
        "truncated": truncated,
        "entry_count": len(entries),
        "pair_class_counts": class_counts,
        "entries": entries,
        "pairs": pairs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("catalog-output/catalog.sqlite3"))
    parser.add_argument("--captures", type=Path, default=Path("private-exports/gelbooru-captures"))
    parser.add_argument(
        "--output", type=Path, default=Path("private-exports/matching-spike/manifest.json")
    )
    parser.add_argument("--no-fxtwitter", action="store_true")
    arguments = parser.parse_args(argv)
    manifest = build_manifest(
        arguments.catalog,
        arguments.captures,
        arguments.output,
        use_fxtwitter=not arguments.no_fxtwitter,
    )
    counts = manifest["pair_class_counts"]
    assert isinstance(counts, dict)
    print(
        f"manifest: {arguments.output} entries={manifest['entry_count']} "
        f"truncated={manifest['truncated']} pairs={sum(counts.values())}"
    )
    for name, count in sorted(counts.items()):
        print(f"  {name}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
