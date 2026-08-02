import json
import zipfile

import pytest

from x_likes.archive import ArchiveError, read_likes


def test_reads_like_js_and_deduplicates(tmp_path):
    payload = [
        {
            "like": {
                "tweetId": "123",
                "fullText": "archived text",
                "expandedUrl": "https://twitter.com/example/status/123",
            }
        },
        {"like": {"tweetId": "123", "expandedUrl": "https://x.com/example/status/123"}},
        {"like": {"expandedUrl": "https://x.com/example/status/456"}},
    ]
    source = tmp_path / "like.js"
    source.write_text(f"window.YTD.like.part0 = {json.dumps(payload)};", encoding="utf-8")

    likes = read_likes(source)

    assert [like.post_id for like in likes] == ["123", "456"]
    assert likes[0].post_url == "https://x.com/example/status/123"
    assert likes[0].archived_text == "archived text"


def test_reads_like_js_from_archive_zip(tmp_path):
    source = tmp_path / "archive.zip"
    payload = [{"like": {"tweetId": "123", "fullText": "hello"}}]
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "twitter-archive/data/like.js",
            f"window.YTD.like.part0 = {json.dumps(payload)};",
        )

    assert read_likes(source)[0].post_url == "https://x.com/i/web/status/123"


def test_reads_split_like_files_from_extracted_archive(tmp_path):
    data = tmp_path / "export" / "data"
    data.mkdir(parents=True)
    for part, post_id in enumerate(("123", "456")):
        payload = [{"like": {"tweetId": post_id}}]
        (data / f"like-part{part}.js").write_text(
            f"window.YTD.like.part{part} = {json.dumps(payload)};",
            encoding="utf-8",
        )

    assert [like.post_id for like in read_likes(tmp_path)] == ["123", "456"]


def test_rejects_unrecognized_nonempty_records(tmp_path):
    source = tmp_path / "like.js"
    source.write_text('window.YTD.like.part0 = [{"like": {"other": true}}];', encoding="utf-8")

    with pytest.raises(ArchiveError, match="no post IDs"):
        read_likes(source)
