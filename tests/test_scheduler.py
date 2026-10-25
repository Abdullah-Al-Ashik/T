from datetime import datetime
from zoneinfo import ZoneInfo
from src.config import load_config
from src.scheduler import due_slots, slot_id

def test_schedule_has_fourteen_slots():
    cfg = load_config()
    assert sum(map(len, cfg["schedule"].values())) == 14

def test_due_slot_uses_new_york_dst():
    schedule = {d: ["11:30", "19:30"] for d in ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]}
    before = datetime(2026, 3, 7, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    after = datetime(2026, 3, 9, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    b = due_slots(before, schedule, "America/New_York", 1)
    a = due_slots(after, schedule, "America/New_York", 1)
    assert b and a
    assert b[-1]["due_at"].endswith("-05:00")
    assert a[-1]["due_at"].endswith("-04:00")

def test_slot_id_stable():
    assert slot_id("2026-10-25", 1) == "2026-10-25-slot-1"


def test_fresh_install_does_not_create_year_of_missed_slots():
    from src.scheduler import unfulfilled_slots
    cfg = load_config()
    now = datetime(2026, 10, 25, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    slots = unfulfilled_slots(cfg, now, set(), "2026-10-25")
    assert all(s["scheduled_at"][:10] == "2026-10-25" for s in slots)
