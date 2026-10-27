import json
import pytest
from src.state_manager import StateManager

def test_state_atomic_persistence_and_history(tmp_path):
    state = StateManager(tmp_path / "state.json", tmp_path / "history.json")
    state.update_job("abc", status="processing", filename="x.mp4")
    state.mark_published("abc", {"video_id":"abc","publication_id":"post-1","status":"completed"})
    assert json.loads((tmp_path / "state.json").read_text())["videos"]["abc"]["status"] == "completed"
    assert json.loads((tmp_path / "history.json").read_text())["posts"][0]["publication_id"] == "post-1"

def test_corrupt_state_is_not_overwritten(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{")
    with pytest.raises(ValueError):
        StateManager(p, tmp_path / "history.json")
