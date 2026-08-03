from dataclasses import replace

from x_likes.archive import ArchivedLike
from x_likes.database import LikesDatabase
from x_likes.provider import AccountMetadata, ImageMetadata, PostMetadata


def test_import_and_save_metadata(tmp_path):
    path = tmp_path / "likes.sqlite3"
    metadata = PostMetadata(
        post_id="123",
        post_url="https://x.com/person/status/123",
        text="current text",
        account=AccountMetadata(
            account_id="7",
            handle="person",
            display_name="Person",
            bio="A useful bio",
            profile_url="https://x.com/person",
            avatar_url="https://pbs.twimg.com/profile_images/person.jpg",
            banner_url=None,
            location="Somewhere",
            website_url="https://example.com",
            followers=120,
            following=30,
            verified=True,
            verification_type="individual",
            raw={"id": "7", "description": "A useful bio"},
        ),
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
            "accounts": 1,
            "fetched": 1,
            "fetch_errors": 0,
            "unavailable": 0,
            "images": 1,
            "downloaded": 0,
        }
        assert database.pending_images()[0].author_handle == "person"
        account = database.connection.execute(
            "SELECT handle, display_name, bio, website_url, verified FROM accounts"
        ).fetchone()
        assert tuple(account) == ("person", "Person", "A useful bio", "https://example.com", 1)

        updated_account = replace(metadata.account, bio="Updated bio", followers=121)
        updated_post = replace(
            metadata,
            post_id="456",
            post_url="https://x.com/person/status/456",
            account=updated_account,
        )
        database.import_likes([ArchivedLike("456", updated_post.post_url)])
        database.save_metadata(updated_post, provider="fxtwitter")

        account_count, bio, followers, account_fetched_at = database.connection.execute(
            "SELECT COUNT(*), bio, followers, fetched_at FROM accounts"
        ).fetchone()
        post_fetched_at = database.connection.execute(
            "SELECT fetched_at FROM posts WHERE post_id = '456'"
        ).fetchone()[0]
        assert (account_count, bio, followers) == (1, "Updated bio", 121)
        assert account_fetched_at == post_fetched_at

        no_account_post = replace(
            metadata,
            post_id="789",
            post_url="https://x.com/i/web/status/789",
            account=None,
        )
        database.import_likes([ArchivedLike("789", no_account_post.post_url)])
        database.save_metadata(no_account_post, provider="fxtwitter")

        assert (
            database.connection.execute(
                "SELECT author_id FROM posts WHERE post_id = '789'"
            ).fetchone()[0]
            is None
        )
        assert database.connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
