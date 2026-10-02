"""Email when a new application is submitted.

Uses plain SMTP (for example Gmail with an app password). Configure with env vars:
SMTP_USER, SMTP_PASSWORD (both required), SMTP_HOST (default smtp.gmail.com),
SMTP_PORT (default 465, SSL), NOTIFY_EMAIL (default: ADMIN_EMAIL).

notify_new_application emails the shop. If SMTP_USER or SMTP_PASSWORD is missing,
nothing is sent.

notify_application_received emails the applicant a short receipt. It stays off
unless ACK_EMAIL_ENABLED=true and SMTP_USER / SMTP_PASSWORD are set. Otherwise it
does nothing. A mail failure never blocks or fails the applicant's submission.
The receipt does not mention age and does not promise when anyone will reply.
References are never emailed.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

log = logging.getLogger("bakery.notify")

SHOP_NAME = "Sunshine's Bakery"
SHOP_ADDRESS = "2231 1st Ave S, Irondale AL 35210"
SHOP_PHONE = "(205) 602-3485"


def _recipient() -> str:
    return (os.environ.get("NOTIFY_EMAIL") or os.environ.get("ADMIN_EMAIL") or "").strip()


def _smtp_login() -> tuple[str, str] | None:
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    if not user or not password:
        return None
    return user, password


def ack_email_enabled() -> bool:
    """True only when ACK_EMAIL_ENABLED is the word true."""
    return os.environ.get("ACK_EMAIL_ENABLED", "").strip().lower() == "true"


def _send_email(msg: EmailMessage, failure_log: str) -> bool:
    creds = _smtp_login()
    if creds is None:
        return False
    user, password = creds
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    try:
        with smtplib.SMTP_SSL(host, port, timeout=10) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 - never break applying because email failed
        log.exception(failure_log)
        return False


def notify_new_application(app_row, position_title: str, applicant_email: str) -> bool:
    creds = _smtp_login()
    to = _recipient()
    if creds is None or not to:
        log.info("New application email skipped: SMTP not configured")
        return False
    user, _password = creds
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
    return _send_email(msg, "New application email failed")


def _one_line(value: str) -> str:
    return " ".join((value or "").split())


def notify_application_received(
    applicant_email: str,
    applicant_name: str,
    position_title: str,
) -> bool:
    """Receipt to the applicant. Disabled unless ACK_EMAIL_ENABLED=true and SMTP is set."""
    try:
        if not ack_email_enabled():
            return False
        creds = _smtp_login()
        if creds is None:
            log.info("Application acknowledgement skipped: SMTP not configured")
            return False
        to = (applicant_email or "").strip()
        if not to or "@" not in to:
            return False
        user, _password = creds
        who = _one_line(applicant_name) or "there"
        role = _one_line(position_title) or "an open role"
        msg = EmailMessage()
        msg["Subject"] = f"{SHOP_NAME}: we received your application"
        msg["From"] = formataddr((SHOP_NAME, user))
        msg["To"] = to
        msg.set_content(
            "\n".join(
                [
                    f"Hi {who},",
                    "",
                    f"We received your application for {role} at {SHOP_NAME}. Thank you for applying.",
                    "",
                    SHOP_NAME,
                    SHOP_ADDRESS,
                    SHOP_PHONE,
                ]
            )
        )
        return _send_email(msg, "Application acknowledgement email failed")
    except Exception:  # noqa: BLE001 - never break applying because email failed
        log.exception("Application acknowledgement email failed")
        return False
