from __future__ import annotations
import argparse, logging, os, shutil, tempfile, time
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from pathlib import Path
from src.config import ROOT, load_config
from src.video_analyzer import discover_videos, stable_video_id, validate_video, extract_frames, public_raw_url
from src.media_storage import preflight_url
from src.caption_generator import generate_caption, GeminiError
from src.threads_publisher import ThreadsPublisher, ThreadsError
from src.state_manager import read_state, write_state_atomic
from src.retry_manager import retry_decision, retry_at
from src.scheduler import unfulfilled_slots
from src.remote_queue import discover_public_video_names, download_public_video

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("threads-publisher")
STATE_PATH = ROOT / "data" / "posting_history.json"


def _notify_system_failure(state: dict, component: str, error_type: str, dry_run: bool) -> int:
    # This automation intentionally sends no emails or external notifications.
    # Failures are recorded in state and visible in GitHub Actions logs.
    LOG.error("System component failed safely: component=%s error_type=%s", component, error_type)
    return 1


def run(dry_run: bool = False) -> int:
    config = load_config()
    dry_run = dry_run or bool(config["queue"].get("dry_run", True))
    state = read_state(STATE_PATH)
    trigger_cron = os.getenv("TRIGGERING_CRON", "")
    if dry_run and trigger_cron == "17 * * * *":
        return 0
    videos_dir = ROOT / config["queue"]["video_directory"]
    owner, repo, branch = (os.getenv(k, "") for k in ("PUBLIC_REPO_OWNER", "PUBLIC_REPO_NAME", "PUBLIC_REPO_BRANCH"))
    remote_mode = all((owner, repo, branch))
    now_dt = datetime.now(timezone.utc)
    local_today = now_dt.astimezone(ZoneInfo(config["timezone"])).date()
    system_state = state.setdefault("system", {})
    initialized_raw = system_state.get("schedule_initialized_at")
    if initialized_raw:
        try:
            schedule_start = date.fromisoformat(initialized_raw)
        except (TypeError, ValueError):
            schedule_start = local_today
    else:
        # A fresh installation should look back at least 2 days to catch any
        # slots from the current week that might have already passed today.
        # The scheduler will still use the actual start date for lookback.
        schedule_start = local_today - timedelta(days=2)
        if not dry_run:
            system_state["schedule_initialized_at"] = schedule_start.isoformat()
            write_state_atomic(STATE_PATH, state)
    overdue = unfulfilled_slots(config, now_dt, set(state["slots"]), schedule_start.isoformat())
    now_iso = now_dt.isoformat()
    # A prior process may have been interrupted after a remote request. Do not blindly repeat it.
    interrupted = [v for v in state["videos"].values() if v.get("status") == "processing"]
    for v in interrupted:
        v["status"] = "reconcile_required"
        v["last_error_category"] = "interrupted_with_remote_outcome_unknown"
    if interrupted:
        write_state_atomic(STATE_PATH, state)
        LOG.error("Found interrupted processing jobs; marked them reconcile_required and will not republish them automatically")
    retryable = [v for v in state["videos"].values() if v.get("status") == "retry_wait" and v.get("next_retry_at") and v["next_retry_at"] <= now_iso]
    if not overdue and not retryable and not dry_run:
        return 0
    jobs_by_name = {v.get("filename"): v for v in state["videos"].values() if v.get("filename")}
    duplicate_names = set(state.get("duplicates", {}).keys())
    queue_names = []
    if remote_mode:
        try:
            queue_names = discover_public_video_names(owner, repo, branch)
        except Exception as exc:
            return _notify_system_failure(state, "queue_discovery", type(exc).__name__, dry_run)
        names = [name for name in queue_names if name not in duplicate_names and jobs_by_name.get(name, {}).get("status") not in {"completed", "processing", "reconcile_required", "failed"}]
    else:
        names = [p.name for p in discover_videos(videos_dir) if p.name not in duplicate_names and jobs_by_name.get(p.name, {}).get("status") not in {"completed", "processing", "reconcile_required", "failed"}]
    active_slot = overdue[0] if overdue and not retryable else None
    if active_slot:
        eligible = [name for name in names if jobs_by_name.get(name, {}).get("status") != "retry_wait"]
    elif retryable:
        retry_names = {v.get("filename") for v in retryable}
        if remote_mode:
            eligible = [name for name in queue_names if name in retry_names]
        else:
            eligible = [p.name for p in discover_videos(videos_dir) if p.name in retry_names]
    else:
        eligible = names if dry_run else []
    if not eligible:
        LOG.info("No eligible due video job found")
        return 0
    video_name = eligible[0]
    work_dir = None
    if remote_mode:
        work_dir = Path(tempfile.mkdtemp(prefix="threads-video-"))
        try:
            video = download_public_video(owner, repo, branch, video_name, work_dir / video_name)
        except Exception as exc:
            shutil.rmtree(work_dir, ignore_errors=True)
            return _notify_system_failure(state, "video_download", type(exc).__name__, dry_run)
    else:
        video = videos_dir / video_name
    validate_video(video)
    video_id = stable_video_id(video)
    if video_id in state["videos"] and state["videos"][video_id].get("status") == "completed" and state["videos"][video_id].get("filename") != video_name:
        state.setdefault("duplicates", {})[video_name] = {"video_id": video_id, "status": "duplicate_content_already_published", "detected_at": datetime.now(timezone.utc).isoformat()}
        write_state_atomic(STATE_PATH, state)
        LOG.warning("Skipping duplicate video content under a new filename; source file is retained for manual cleanup")
        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
        return 0
    now = datetime.now(timezone.utc).isoformat()
    job_slot_id = active_slot["slot_id"] if active_slot else None
    job_slot_at = active_slot["scheduled_at"] if active_slot else None
    job = state["videos"].setdefault(video_id, {"video_id": video_id, "filename": video.name, "status": "pending", "attempts": 0, "caption": None})
    job["filename"] = video_name
    if not job_slot_id and job.get("scheduled_slot"):
        job_slot_id, job_slot_at = job.get("scheduled_slot"), job.get("scheduled_at")
    job["last_attempt_at"] = now
    if job_slot_id:
        job["scheduled_slot"] = job_slot_id
        job["scheduled_at"] = job_slot_at
    job["attempts"] = int(job.get("attempts", 0)) + 1
    try:
        frames, timestamps = extract_frames(video, config["ai"]["max_frames"], config["ai"]["sample_window_seconds"])
        caption = job.get("caption")
        ai_ok = bool(caption)
        if not caption and (not dry_run or config["queue"].get("dry_run_ai", False)):
            ai_backoffs = config["ai"].get("backoff_seconds", [5, 15])
            ai_attempts = max(1, int(config["ai"].get("max_attempts", 3)))
            for ai_attempt in range(ai_attempts):
                try:
                    caption = generate_caption(frames, os.getenv("AI_API_KEY", ""), config["ai"]["model"], config["ai"]["endpoint"], config["ai"]["max_caption_chars"], config["ai"]["max_hashtags"])
                    ai_ok = True
                    break
                except GeminiError as exc:
                    # Retry only transient failures; honor Retry-After and never log the exception body.
                    if not exc.transient or ai_attempt >= ai_attempts - 1 or (exc.retry_after_seconds is not None and exc.retry_after_seconds > 300):
                        LOG.warning("Caption generation failed; applying empty-caption fallback (category=%s)", exc.category)
                        caption, ai_ok = "", False
                        break
                    delay = exc.retry_after_seconds if exc.retry_after_seconds is not None else (ai_backoffs[min(ai_attempt, len(ai_backoffs) - 1)] if ai_backoffs else 5)
                    LOG.warning("Transient caption API failure; retrying after %s seconds (category=%s)", delay, exc.category)
                    time.sleep(delay)
                except Exception as exc:
                    LOG.warning("Caption generation failed; applying empty-caption fallback (error_type=%s)", type(exc).__name__)
                    caption, ai_ok = "", False
                    break
        if dry_run:
            raw_url = public_raw_url(owner or "owner", repo or "repo", branch or "main", video_name)
            job.update({"status": "pending", "last_error": None, "dry_run_at": now, "frame_timestamps": timestamps})
            return 0
        if not all((owner, repo, branch)):
            raise ValueError("PUBLIC_REPO_OWNER, PUBLIC_REPO_NAME and PUBLIC_REPO_BRANCH must be configured")
        url = public_raw_url(owner, repo, branch, video_name)
        if not preflight_url(url):
            raise ThreadsError("media_url_unavailable", "Public video URL failed unauthenticated preflight", transient=True)
        job.update({"status": "processing", "caption": caption, "caption_generation_succeeded": ai_ok, "frame_timestamps": timestamps})
        # Mark the slot as claimed *before* calling the Threads API so that
        # any concurrent or queued workflow run that reads this state file
        # will see the slot is already taken and skip it.
        if job_slot_id:
            state["slots"][job_slot_id] = {"video_id": video_id, "filename": video_name, "status": "processing", "claimed_at": now}
        write_state_atomic(STATE_PATH, state)
        publisher = ThreadsPublisher(os.getenv("THREADS_USER_ID", ""), os.getenv("THREADS_ACCESS_TOKEN", ""), config["threads"]["graph_base_url"])
        result = None
        backoffs = config["threads"].get("backoff_seconds", [30, 120, 300])
        for immediate_attempt in range(config["threads"]["max_attempts_per_run"]):
            try:
                if immediate_attempt:
                    job["attempts"] = int(job.get("attempts", 0)) + 1
                result = publisher.publish_video(url, caption or "", config["threads"]["processing_poll_seconds"], config["threads"]["processing_timeout_seconds"])
                break
            except ThreadsError as retry_exc:
                if retry_exc.ambiguous or not retry_exc.transient or immediate_attempt >= config["threads"]["max_attempts_per_run"] - 1:
                    raise
                if retry_exc.retry_after_seconds is not None and retry_exc.retry_after_seconds > 1800:
                    raise
                delay = retry_exc.retry_after_seconds if retry_exc.retry_after_seconds is not None else (backoffs[min(immediate_attempt, len(backoffs) - 1)] if backoffs else 60)
                LOG.warning("Transient Threads failure; retrying after %s seconds (category=%s)", delay, retry_exc.category)
                time.sleep(delay)
        if result is None:
            raise ThreadsError("publication_unconfirmed", "Publishing did not produce a confirmed result", ambiguous=True)
        completed_at = datetime.now(timezone.utc).isoformat()
        job.update({"status": "completed", "published_at": completed_at, "publication_id": result["publication_id"], "container_id": result["container_id"], "last_error": None})
        state["pending_deletions"].append(video_name)
        if job_slot_id:
            state["slots"][job_slot_id] = {"video_id": video_id, "filename": video_name, "publication_id": result["publication_id"], "status": "published", "published_at": completed_at, "claimed_at": now}
        write_state_atomic(STATE_PATH, state)
        return 0
    except Exception as exc:
        err = exc if isinstance(exc, ThreadsError) else None
        category = err.category if err else type(exc).__name__
        decision = retry_decision(err or RuntimeError(category), job["attempts"], config["threads"]["max_attempts_per_run"])
        next_status = "reconcile_required" if decision.get("reconcile_first") else ("retry_wait" if decision.get("background_retry") or decision.get("retry") else "failed")
        # Release the slot claim on non-ambiguous failures so the slot can
        # be retried.  Ambiguous failures keep the claim (reconcile_required)
        # to prevent a duplicate publish.
        if job_slot_id and not decision.get("reconcile_first"):
            state["slots"].pop(job_slot_id, None)
        retry_minutes = config["threads"]["background_retry_minutes"]
        if err and err.retry_after_seconds is not None:
            retry_minutes = max(retry_minutes, (err.retry_after_seconds + 59) // 60)
        job.update({"status": next_status, "last_error_category": category, "last_error_at": datetime.now(timezone.utc).isoformat(), "last_safe_to_retry": decision.get("retry", False), "next_retry_at": retry_at(datetime.now(timezone.utc), retry_minutes) if next_status == "retry_wait" else None})
        write_state_atomic(STATE_PATH, state)
        LOG.error("Job failed safely: video_id=%s error_category=%s retry=%s reconcile_first=%s", video_id[:12], category, decision.get("retry"), decision.get("reconcile_first"))
        return 1
    finally:
        # Frames are temporary and do not contain credentials; clean local scratch files.
        if config.get("queue", {}).get("cleanup_temp_media", True):
            if "frames" in locals() and frames:
                for p in frames:
                    shutil.rmtree(p.parent, ignore_errors=True)
            if "work_dir" in locals() and work_dir:
                shutil.rmtree(work_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Threads video publisher")
    parser.add_argument("--dry-run", action="store_true", help="Never publish or delete videos")
    args = parser.parse_args()
    config = load_config()
    dry_run = args.dry_run or bool(config["queue"].get("dry_run", True))
    max_jobs = 1 if dry_run else max(1, int(config["queue"].get("max_jobs_per_run", 1)))
    for _ in range(max_jobs):
        before = read_state(STATE_PATH)
        before_completed = sum(1 for job in before["videos"].values() if job.get("status") == "completed")
        result = run(dry_run=args.dry_run)
        if result != 0:
            raise SystemExit(result)
        if dry_run:
            break
        after = read_state(STATE_PATH)
        after_completed = sum(1 for job in after["videos"].values() if job.get("status") == "completed")
        if after_completed <= before_completed:
            break
    raise SystemExit(0)

if __name__ == "__main__":
    main()
