import pytest
from src.media_storage import public_video_url, preflight_url

def test_public_url_construction():
    assert public_video_url("https://raw.githubusercontent.com/acct/repo/main", "my video.mp4") == "https://raw.githubusercontent.com/acct/repo/main/videos/my%20video.mp4"

def test_rejects_unsafe_filename():
    with pytest.raises(ValueError):
        public_video_url("https://raw.githubusercontent.com/acct/repo/main", "../secret.mp4")

def test_preflight_requires_video_content_type():
    class Response:
        status_code = 206
        headers = {"Content-Type": "video/mp4"}
        def close(self): pass
    class Session:
        def get(self, *args, **kwargs): return Response()
    assert preflight_url("https://raw.githubusercontent.com/x/y/z/a.mp4", session=Session())
