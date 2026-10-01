"""Email Ronald when a new application is submitted.

Uses plain SMTP (for example Gmail with an app password). Configure with env vars:
SMTP_USER, SMTP_PASSWORD (both required), SMTP_HOST (default smtp.gmail.com),
SMTP_PORT (default 465, SSL), NOTIFY_EMAIL (default: ADMIN_EMAIL).
If SMTP_USER or SMTP_PASSWORD is missing, nothing is sent. A mail failure never
blocks or fails the applicant's submission.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger("bakery.notify")


def _recipient() -> str:
    return (os.environ.get("NOTIFY_EMAIL") or os.environ.get("ADMIN_EMAIL") or "").strip()


def notify_new_application(app_row, position_title: str, applicant_email: str) -> bool:
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    to = _recipient()
    if not user or not password or not to:
        log.info("New application email skipped: SMTP not configured")
        return False
    msg = EmailMessage()
    msg["Subject"] = f"New application: {app_row.name} for {position_title}"
    msg["From"] = user
    msg["To"] = to
    lines = [
        f"{app_row.name} just applied for {position_title}.",
        "",
        f"Phone: {app_row.phone}",
        f"Email: {applicant_email}",
        f"Hours per week: {app_row.hours_per_week}",
        f"Available to start: {app_row.start_date}",
        f"Availability: {app_row.availability}",
        f"Worked a counter before: {app_row.prior_counter}"
        + (f" ({app_row.prior_where})" if app_row.prior_where else ""),
        f"Why this shop: {app_row.why_shop}",
        "",
        "Review in admin: https://bakery-apply-k6uuoen7wa-ue.a.run.app/admin",
    ]
    msg.set_content("\n".join(lines))
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    try:
        with smtplib.SMTP_SSL(host, port, timeout=10) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 - never break applying because email failed
        log.exception("New application email failed")
        return False
