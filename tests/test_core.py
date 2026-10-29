import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
from src.config import load_config
from src.scheduler import due_slots
from src.video_analyzer import discover_videos, stable_video_id, public_raw_url, validate_video
from src.caption_generator import _parse_json, build_caption_text
from src.state_manager import empty_state, validate_state, write_state_atomic, read_state, safe_video_path
from src.retry_manager import retry_decision
from src.threads_publisher import ThreadsError

ROOT = Path(__file__).resolve().parents[1]


def test_config_has_fourteen_slots_and_fixed_ai():
    cfg = load_config(ROOT / "config.json")
    assert sum(map(len, cfg["schedule"].values())) == 14
    assert cfg["ai"]["model"] == "gemini-3.5-flash-lite"


def test_dst_timezone_slots():
    cfg = load_config(ROOT / "config.json")
    winter = due_slots(cfg, datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc), 24)
    summer = due_slots(cfg, datetime(2026, 7, 6, 15, 0, tzinfo=timezone.utc), 24)
    assert winter and summer
    assert winter[0]["scheduled_at"].endswith("-05:00")
    assert summer[0]["scheduled_at"].endswith("-04:00")


def test_video_discovery_and_hash(tmp_path):
    d = tmp_path / "videos"; d.mkdir()
    (d / "b.MP4").write_bytes(b"video-b" * 200)
    (d / "a.mp4").write_bytes(b"video-a" * 200)
    (d / ".hidden.mp4").write_bytes(b"hidden" * 200)
    (d / "ignore.avi").write_bytes(b"unsupported")
    found = discover_videos(d)
    assert [p.name for p in found] == ["a.mp4", "b.MP4"]
    assert stable_video_id(found[0]) == stable_video_id(found[0])
    validate_video(found[0])
    with pytest.raises(ValueError): validate_video(d / "ignore.avi")


def test_public_raw_url_and_path_traversal():
    url = public_raw_url("user", "repo", "main", "a clip.mp4")
    assert url == "https://raw.githubusercontent.com/user/repo/main/videos/a%20clip.mp4"
    with pytest.raises(ValueError): public_raw_url("user", "repo", "main", "../secret.mp4")


def test_caption_parse_and_length():
    data = _parse_json('```json\n{"caption":"Look at this scene!","hashtags":["travel","#Travel","#Nature","bad tag"]}\n```')
    assert data["hashtags"] == ["#travel", "#Nature"]
    result = build_caption_text({"caption": "word " * 100, "hashtags": ["#Travel"]}, 80, 3)
    assert len(result) <= 80
    assert "#Travel" in result


def test_state_atomic_round_trip_and_reject_unsafe_delete(tmp_path):
    path = tmp_path / "state.json"
    state = empty_state(); state["pending_deletions"] = ["video.mp4"]
    write_state_atomic(path, state)
    assert read_state(path)["pending_deletions"] == ["video.mp4"]
    state["pending_deletions"] = ["../secrets.txt"]
    with pytest.raises(ValueError): validate_state(state)
    with pytest.raises(ValueError): safe_video_path("../secrets.txt")


def test_retry_does_not_repeat_ambiguous_publish():
    e = ThreadsError("timeout", "safe", transient=True, ambiguous=True)
    decision = retry_decision(e, 1)
    assert decision["retry"] is False and decision["reconcile_first"] is True


def test_permanent_errors_not_background_retried():
    e = ThreadsError("auth", "safe", transient=False)
    assert retry_decision(e, 4)["retry"] is False
