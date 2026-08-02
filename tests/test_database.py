from x_likes.archive import ArchivedLike
from x_likes.database import LikesDatabase
from x_likes.provider import ImageMetadata, PostMetadata


def test_import_and_save_metadata(tmp_path):
    path = tmp_path / "likes.sqlite3"
    metadata = PostMetadata(
        post_id="123",
        post_url="https://x.com/person/status/123",
        text="current text",
        author_id="7",
        author_handle="person",
        author_name="Person",
        created_at=None,
        images=(ImageMetadata(1, "https://example.com/image.jpg", 10, 20, "alt"),),
        raw={"tweet": {"id": "123"}},
    )

    with LikesDatabase(path) as database:
        database.import_likes([ArchivedLike("123", "https://x.com/i/web/status/123", "old")])
        assert database.posts_to_fetch() == ["123"]

        database.save_metadata(metadata, provider="fxtwitter")

        assert database.posts_to_fetch() == []
        assert database.summary() == {
            "posts": 1,
            "fetched": 1,
            "fetch_errors": 0,
            "unavailable": 0,
            "images": 1,
            "downloaded": 0,
        }
        assert database.pending_images()[0].author_handle == "person"
