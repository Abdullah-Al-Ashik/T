from src.commit_state import merge_states
from src.state_manager import empty_state


def test_merge_preserves_remote_completed_record_over_stale_artifact():
    current = empty_state()
    current["videos"]["hash1"] = {"video_id": "hash1", "filename": "clip.mp4", "status": "completed", "publication_id": "post-1"}
    incoming = empty_state()
    incoming["videos"]["hash1"] = {"video_id": "hash1", "filename": "clip.mp4", "status": "processing"}
    merged = merge_states(current, incoming)
    assert merged["videos"]["hash1"]["status"] == "completed"
    assert merged["videos"]["hash1"]["publication_id"] == "post-1"


def test_merge_unions_pending_deletions_and_slots():
    current = empty_state()
    current["pending_deletions"] = ["a.mp4"]
    current["slots"]["slot-a"] = {"status": "published", "publication_id": "post-a"}
    incoming = empty_state()
    incoming["pending_deletions"] = ["b.mp4"]
    incoming["slots"]["slot-b"] = {"status": "published", "publication_id": "post-b"}
    merged = merge_states(current, incoming)
    assert merged["pending_deletions"] == ["a.mp4", "b.mp4"]
    assert set(merged["slots"]) == {"slot-a", "slot-b"}
