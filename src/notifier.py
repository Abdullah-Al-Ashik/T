from __future__ import annotations
import os, smtplib
from email.message import EmailMessage
from collections.abc import Mapping


def _send(subject: str, body: str, values: Mapping[str, str]) -> bool:
    host = values.get("SMTP_HOST", "smtp.gmail.com")
    try:
        port = int(values.get("SMTP_PORT", "587"))
    except (ValueError, TypeError):
        return False
    username = values.get("SMTP_USERNAME", "")
    password = values.get("SMTP_APP_PASSWORD", "")
    recipient = values.get("NOTIFY_EMAIL_TO", "")
    if not all((host, username, password, recipient)):
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject[:180], username, recipient
    msg.set_content(body[:8000])
    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException):
        # Never log SMTP exceptions; some implementations may include server details.
        return False


def send_failure_email(subject: str, body: str) -> bool:
    return _send(subject, body, os.environ)


def send_notification(subject: str, body: str, environ=None) -> bool:
    """Send using environment configuration; returns False when config is missing."""
    return _send(subject, body, os.environ if environ is None else environ)
