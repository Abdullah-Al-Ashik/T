from __future__ import annotations
import json, os, tempfile
from pathlib import Path
from typing import Any

STATE_SCHEMA_VERSION = 1


def empty_state() -> dict:
    return {"schema_version": STATE_SCHEMA_VERSION, "videos": {}, "slots": {}, "pending_deletions": [], "system": {}}


def validate_state(data: Any) -> dict:
    if not isinstance(data, dict) or data.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError("State schema is invalid or unsupported")
    if not isinstance(data.get("slots"), dict):
        raise ValueError("State field slots must be an object")
    if not isinstance(data.get("videos", data.get("jobs")), dict):
        raise ValueError("State field videos/jobs must be an object")
    if not isinstance(data.get("pending_deletions", []), list):
        raise ValueError("pending_deletions must be a list")
    for filename in data.get("pending_deletions", []):
        safe_video_path(filename)
    return data


def safe_video_path(filename: str) -> Path:
    if not isinstance(filename, str) or not filename or filename.startswith(".") or "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError("Unsafe video filename")
    return Path("videos") / filename


def read_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    try:
        return validate_state(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("State file is corrupt or unreadable; refusing to overwrite it") from exc


def write_state_atomic(path: Path, data: dict) -> None:
    validate_state(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

class StateManager:
    """Small atomic state/history manager retained for focused unit/integration tests."""
    def __init__(self, state_path: Path, history_path: Path):
        self.state_path = Path(state_path)
        self.history_path = Path(history_path)
        self.state = self._load(self.state_path, {"schema_version": 1, "jobs": {}, "slots": {}})
        self.history = self._load(self.history_path, {"schema_version": 1, "posts": []})
        if not isinstance(self.state.get("jobs"), dict) or not isinstance(self.history.get("posts"), list):
            raise ValueError("State or history schema is invalid")

    @staticmethod
    def _load(path: Path, default: dict) -> dict:
        if not path.exists():
            return default
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError("State file is corrupt; refusing to overwrite") from exc
        if not isinstance(data, dict):
            raise ValueError("State file must contain a JSON object")
        return data

    def update_job(self, job_id: str, **fields) -> None:
        if not job_id or not isinstance(job_id, str):
            raise ValueError("job_id is required")
        job = self.state["jobs"].setdefault(job_id, {"job_id": job_id, "status": "pending"})
        job.update(fields)
        write_state_atomic(self.state_path, {"schema_version": 1, "jobs": self.state["jobs"], "slots": self.state.get("slots", {})})

    def mark_published(self, job_id: str, record: dict) -> None:
        if not record.get("publication_id"):
            raise ValueError("publication_id is required to mark a job published")
        job = self.state["jobs"].setdefault(job_id, {"job_id": job_id})
        job.update(record)
        job["status"] = "completed"
        if not any(p.get("publication_id") == record["publication_id"] for p in self.history["posts"]):
            self.history["posts"].append(dict(record))
        write_state_atomic(self.state_path, {"schema_version": 1, "jobs": self.state["jobs"], "slots": self.state.get("slots", {})})
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.history_path.name}.", suffix=".tmp", dir=self.history_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, sort_keys=True); f.write("\n"); f.flush(); os.fsync(f.fileno())
            os.replace(temp_name, self.history_path)
        finally:
            if os.path.exists(temp_name): os.unlink(temp_name)
