from __future__ import annotations
from datetime import datetime, timezone, timedelta


def retry_decision(error, attempts: int, max_attempts: int = 4) -> dict:
    """One initial attempt plus up to three retries by default."""
    if getattr(error, "ambiguous", False):
        return {"retry": False, "reconcile_first": True, "reason": "ambiguous_remote_outcome"}
    if not getattr(error, "transient", False):
        return {"retry": False, "reconcile_first": False, "reason": getattr(error, "category", "permanent_error")}
    if attempts >= max_attempts:
        return {"retry": False, "reconcile_first": False, "reason": "immediate_retry_limit_reached", "background_retry": True}
    return {"retry": True, "reconcile_first": False, "reason": "transient_error"}


def retry_at(now: datetime, minutes: int = 60) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now + timedelta(minutes=minutes)).isoformat()


def retry_delay_seconds(attempt: int, base_seconds: int = 30, max_seconds: int = 300) -> int:
    return min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))

def is_permanent_error(error: Exception) -> bool:
    if hasattr(error, "retryable"):
        return not bool(error.retryable)
    if hasattr(error, "transient"):
        return not bool(getattr(error, "transient"))
    if isinstance(error, RuntimeError):
        return False
    return not bool(getattr(error, "transient", False))
