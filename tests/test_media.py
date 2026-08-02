from io import BytesIO

import httpx
from PIL import Image

from x_likes.database import PendingImage
from x_likes.media import download_image


def test_downloads_and_hashes_image(tmp_path):
    content = BytesIO()
    Image.new("RGB", (16, 16), color=(20, 40, 60)).save(content, format="PNG")

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=content.getvalue(),
        )

    image = PendingImage("123", 1, "https://pbs.twimg.com/media/image", "some/person")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = download_image(image, output_root=tmp_path, client=client)

    assert result.local_path == tmp_path / "some_person" / "123_01.png"
    assert result.file_size == len(content.getvalue())
    assert len(result.md5) == 32
    assert len(result.sha256) == 64
    assert len(result.phash) == 16


def test_rejects_unexpected_image_host(tmp_path):
    image = PendingImage("123", 1, "https://example.test/image.png", "person")
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
        try:
            download_image(image, output_root=tmp_path, client=client)
        except ValueError as error:
            assert "unexpected image host" in str(error)
        else:
            raise AssertionError("unexpected image host was accepted")
