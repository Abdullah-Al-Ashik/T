from __future__ import annotations
import os, sys
from datetime import datetime, timezone
from src.notifier import send_notification


def main() -> int:
    required = ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_APP_PASSWORD", "NOTIFY_EMAIL_TO")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        print("Email test cannot run; missing Actions Secrets: " + ", ".join(missing))
        return 2
    body = "This is a test message from the Threads video publisher.\nNo Threads post was created.\nTest time: " + datetime.now(timezone.utc).isoformat()
    if not send_notification("Threads publisher email test", body):
        print("Email test failed. SMTP details are intentionally omitted from logs.")
        return 1
    print("Email test message sent successfully. Check the configured recipient inbox.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
