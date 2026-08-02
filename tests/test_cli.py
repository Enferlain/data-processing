import json
import sqlite3

import pytest

from x_likes.cli import main


def test_import_only_cli_creates_database(tmp_path, capsys):
    source = tmp_path / "like.js"
    source.write_text(
        f"window.YTD.like.part0 = {json.dumps([{'like': {'tweetId': '123'}}])};",
        encoding="utf-8",
    )
    output = tmp_path / "output"

    main([str(source), "--output", str(output), "--import-only"])

    with sqlite3.connect(output / "likes.sqlite3") as connection:
        assert connection.execute("SELECT post_id FROM posts").fetchone() == ("123",)
    assert "Imported 1 unique likes" in capsys.readouterr().out


def test_cli_rejects_import_only_with_downloads(tmp_path):
    with pytest.raises(SystemExit, match="cannot be combined"):
        main([str(tmp_path / "missing.zip"), "--import-only", "--download-images"])
