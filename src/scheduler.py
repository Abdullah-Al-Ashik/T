from __future__ import annotations
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
DAY_KEYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def slot_id(local_date: str, slot_number: int) -> str:
    return f"{local_date}-slot-{slot_number}"


def due_slots(config_or_now, now_or_schedule=None, timezone_name="America/New_York", lookback_days=1, *, lookback_hours=None) -> list[dict]:
    """Support due_slots(config, now, lookback_hours=...) and due_slots(now, schedule, timezone, days)."""
    if isinstance(config_or_now, datetime):
        now = config_or_now
        schedule = now_or_schedule
        tz = ZoneInfo(timezone_name)
        hours = lookback_hours if lookback_hours is not None else lookback_days * 24
    else:
        config = config_or_now
        now = now_or_schedule
        schedule = config["schedule"]
        tz = ZoneInfo(config.get("timezone", "America/New_York"))
        hours = lookback_hours if lookback_hours is not None else 24 * 2
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    local_now = now.astimezone(tz)
    start = local_now - timedelta(hours=hours)
    out = []
    d = start.date()
    while d <= local_now.date():
        day_name = DAY_KEYS[d.weekday()]
        for idx, hhmm in enumerate(schedule[day_name], start=1):
            hh, mm = map(int, hhmm.split(":"))
            candidate = datetime.combine(d, time(hh, mm), tz)
            if start < candidate <= local_now:
                sid = slot_id(d.isoformat(), idx)
                out.append({"slot_id": sid, "scheduled_at": candidate.isoformat(), "due_at": candidate.isoformat(), "day": day_name, "slot_number": idx})
        d += timedelta(days=1)
    return sorted(out, key=lambda x: x["scheduled_at"])


def next_retry_at(now: datetime, minutes: int) -> str:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return (now + timedelta(minutes=minutes)).isoformat()


def unfulfilled_slots(config: dict, now: datetime, fulfilled_slot_ids: set[str], start_date: str) -> list[dict]:
    """Return overdue slots since the installation start date, never inventing pre-install backlog."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    tz = ZoneInfo(config.get("timezone", "America/New_York"))
    local_today = now.astimezone(tz).date()
    try:
        first_day = date.fromisoformat(start_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("start_date must be an ISO date") from exc
    lookback_days = max(1, (local_today - first_day).days + 1)
    return [slot for slot in due_slots(config, now, lookback_hours=24 * lookback_days)
            if slot["scheduled_at"][:10] >= first_day.isoformat() and slot["slot_id"] not in fulfilled_slot_ids]
