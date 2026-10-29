from pathlib import Path
import pytest
from src.video_analyzer import discover_videos, stable_video_id, validate_video

def test_discovery_sorted_and_ignores_hidden(tmp_path):
    (tmp_path / "z.mp4").write_bytes(b"z" * 1500)
    (tmp_path / "a.MP4").write_bytes(b"a" * 1500)
    (tmp_path / ".hidden.mp4").write_bytes(b"h" * 1500)
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "temp.mp4.part").write_bytes(b"p")
    assert [p.name for p in discover_videos(tmp_path)] == ["a.MP4", "z.mp4"]

def test_stable_id_content_based(tmp_path):
    p = tmp_path / "one.mp4"
    p.write_bytes(b"sample")
    a = stable_video_id(p)
    p.rename(tmp_path / "two.mp4")
    assert stable_video_id(tmp_path / "two.mp4") == a

def test_validation_rejects_empty_and_wrong_extension(tmp_path):
    p = tmp_path / "empty.mp4"
    p.write_bytes(b"")
    with pytest.raises(ValueError):
        validate_video(p)
    q = tmp_path / "x.mov"
    q.write_bytes(b"x")
    with pytest.raises(ValueError):
        validate_video(q)
