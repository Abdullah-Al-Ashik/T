from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"


def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Configuration file is missing or invalid JSON") from exc
    if config.get("timezone") != "America/New_York":
        raise ValueError("timezone must remain America/New_York unless intentionally reconfigured")
    slots = config.get("schedule", {})
    if len(slots) != 7 or any(not isinstance(v, list) or len(v) != 2 for v in slots.values()):
        raise ValueError("Schedule must define exactly two slots for each of seven days")
    times = [t for day in slots.values() for t in day]
    if len(times) != 14 or len(set(times)) < 7:
        raise ValueError("Expected 14 configured weekly slot entries")
    ai = config.get("ai", {})
    if ai.get("model") != "gemini-3.5-flash-lite":
        raise ValueError("The required Gemini model must not be silently replaced")
    if ai.get("endpoint") != "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions":
        raise ValueError("The required Gemini endpoint must not be silently replaced")
    return config
