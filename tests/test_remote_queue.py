import io, json
from pathlib import Path
from src import remote_queue

class FakeResponse:
    def __init__(self, body, headers=None):
        self.body = body
        self.headers = headers or {"Content-Type": "application/json"}
        self.status = 200
    def read(self, n=-1):
        if n == -1:
            data, self.body = self.body, b""
            return data
        data, self.body = self.body[:n], self.body[n:]
        return data
    def __enter__(self): return self
    def __exit__(self, *args): pass


def test_public_queue_listing_filters_and_sorts(monkeypatch):
    payload = [
        {"type": "file", "name": "z.mp4", "size": 2000},
        {"type": "file", "name": "a.MP4", "size": 1500},
        {"type": "dir", "name": "nested", "size": 0},
        {"type": "file", "name": ".hidden.mp4", "size": 1500},
        {"type": "file", "name": "huge.mp4", "size": 999999999},
        {"type": "file", "name": "notes.txt", "size": 5},
    ]
    monkeypatch.setattr(remote_queue, "urlopen", lambda *a, **k: FakeResponse(json.dumps(payload).encode()))
    assert remote_queue.discover_public_video_names("acct", "repo", "main") == ["a.MP4", "z.mp4"]


def test_download_uses_size_limit_and_public_raw_url(monkeypatch, tmp_path):
    data = b"fake-video-bytes"
    monkeypatch.setattr(remote_queue, "urlopen", lambda *a, **k: FakeResponse(data, {"Content-Type": "video/mp4"}))
    out = remote_queue.download_public_video("acct", "repo", "main", "clip.mp4", tmp_path / "clip.mp4")
    assert out.read_bytes() == data
