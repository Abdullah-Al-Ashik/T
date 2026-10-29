from __future__ import annotations
import json, os, subprocess
from pathlib import Path
from src.state_manager import validate_state, safe_video_path, write_state_atomic, read_state, empty_state

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = Path(os.getenv("STATE_ARTIFACT_DIR", "/tmp/publisher-state"))


def merge_states(current: dict, incoming: dict) -> dict:
    """Merge an artifact into latest repository state without downgrading completed jobs."""
    current = validate_state(dict(current))
    incoming = validate_state(dict(incoming))
    merged = dict(current)
    merged["schema_version"] = current["schema_version"]
    for key in ("videos", "slots"):
        left = dict(current.get(key, {}))
        for item_id, item in incoming.get(key, {}).items():
            old = left.get(item_id)
            if isinstance(old, dict) and isinstance(item, dict):
                if key == "videos" and old.get("status") == "completed" and item.get("status") != "completed":
                    continue
                if key == "videos" and old.get("status") == "completed" and item.get("status") == "completed" and old.get("publication_id") and old.get("publication_id") != item.get("publication_id"):
                    continue
                if key == "slots" and old.get("status") == "published" and item.get("status") != "published":
                    continue
                # Do not let a stale incoming state overwrite a slot that is
                # already being processed or published.
                if key == "slots" and old.get("status") in {"processing", "published"} and item.get("status") not in {"processing", "published"}:
                    continue
                left[item_id] = {**old, **item}
            else:
                left[item_id] = item
        merged[key] = left
    merged["pending_deletions"] = sorted(set(current.get("pending_deletions", [])) | set(incoming.get("pending_deletions", [])))
    merged["duplicates"] = {**current.get("duplicates", {}), **incoming.get("duplicates", {})}
    merged["system"] = {**current.get("system", {}), **incoming.get("system", {})}
    return validate_state(merged)


def _stage_and_commit(state: dict, branch: str) -> bool:
    deletions = list(state.get("pending_deletions", []))
    for name in deletions:
        safe_video_path(name)
        matching = [j for j in state["videos"].values() if j.get("filename") == name and j.get("status") == "completed" and j.get("publication_id")]
        if not matching:
            raise ValueError("Deletion requested without a confirmed completed publication")
    target_state = ROOT / "data" / "posting_history.json"
    state_to_persist = dict(state)
    state_to_persist["pending_deletions"] = []
    write_state_atomic(target_state, state_to_persist)
    for name in deletions:
        # Sparse checkout excludes video blobs; --sparse stages their deletion from the index.
        subprocess.run(["git", "rm", "--cached", "--sparse", "--ignore-unmatch", "--", str(safe_video_path(name))], cwd=ROOT, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "data/posting_history.json"], cwd=ROOT, check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if diff.returncode == 0:
        print("No repository state changes to commit")
        return False
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", "chore: persist publisher state and confirmed queue cleanup"], cwd=ROOT, check=True)
    env = os.environ.copy()
    token = env.pop("GH_PUSH_TOKEN", "")
    if not token:
        raise ValueError("GH_PUSH_TOKEN is missing")
    askpass = ROOT / ".git" / "actions-askpass.sh"
    askpass.write_text("#!/bin/sh\ncase \"$1\" in *Username*) echo x-access-token ;; *) printf '%s' \"$GH_PUSH_TOKEN\" ;; esac\n", encoding="utf-8")
    askpass.chmod(0o700)
    env["GH_PUSH_TOKEN"] = token
    env["GIT_ASKPASS"] = str(askpass)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        subprocess.run(["git", "push", "origin", f"HEAD:{branch}"], cwd=ROOT, env=env, check=True, timeout=90, capture_output=True, text=True)
    finally:
        try: askpass.unlink()
        except OSError: pass
    print("Repository state persisted")
    return True


def main() -> int:
    artifact_state = ARTIFACT / "posting_history.json"
    if not artifact_state.is_file():
        print("No state artifact found; refusing to modify repository")
        return 2
    incoming = validate_state(json.loads(artifact_state.read_text(encoding="utf-8")))
    branch = os.getenv("DEFAULT_BRANCH", "main")
    for attempt in range(1, 4):
        current = read_state(ROOT / "data" / "posting_history.json")
        merged = merge_states(current, incoming)
        try:
            _stage_and_commit(merged, branch)
            return 0
        except subprocess.CalledProcessError:
            if attempt >= 3:
                # Do not print raw subprocess output; it may contain sensitive transport diagnostics.
                raise RuntimeError("Repository state push failed after three safe attempts")
            subprocess.run(["git", "fetch", "origin", branch], cwd=ROOT, check=True, capture_output=True, text=True, timeout=90)
            subprocess.run(["git", "reset", "--hard", f"origin/{branch}"], cwd=ROOT, check=True, capture_output=True, text=True, timeout=90)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
