import asyncio
import smtplib
from datetime import UTC, datetime, time, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.models.account import User
from app.models.applications import Notification
from app.models.automation import AutomationSettings


def in_quiet_hours(now: datetime, settings: AutomationSettings) -> bool:
    if not settings.quiet_start or not settings.quiet_end:
        return False
    local = now.astimezone(ZoneInfo(settings.timezone)).time().replace(tzinfo=None)
    start, end = time.fromisoformat(settings.quiet_start), time.fromisoformat(settings.quiet_end)
    return start <= local < end if start <= end else local >= start or local < end


async def enqueue(session, user_id, notification_type: str, payload: dict, dedupe_key: str) -> Notification | None:
    prefs = await session.scalar(select(AutomationSettings).where(AutomationSettings.user_id == user_id))
    email_enabled = bool(prefs and prefs.email_enabled)
    statement = insert(Notification).values(user_id=user_id, notification_type=notification_type, payload=payload,
        dedupe_key=dedupe_key, delivery_status="PENDING" if email_enabled else "SKIPPED")
    statement = statement.on_conflict_do_nothing(index_elements=[Notification.dedupe_key]).returning(Notification.id)
    identifier = await session.scalar(statement)
    return await session.get(Notification, identifier) if identifier else None


def _smtp_send(recipient: str, subject: str, body: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password or "")
        client.send_message(message)


async def deliver_outbox(session, limit: int = 50) -> int:
    settings = get_settings()
    if not (settings.smtp_host and settings.smtp_from_email):
        return 0
    now = datetime.now(UTC)
    rows = list(await session.scalars(select(Notification).where(Notification.delivery_status == "PENDING", Notification.delivery_attempts < 5,
        (Notification.next_attempt_at.is_(None) | (Notification.next_attempt_at <= now))).order_by(Notification.created_at).with_for_update(skip_locked=True).limit(limit)))
    delivered = 0
    for item in rows:
        prefs = await session.scalar(select(AutomationSettings).where(AutomationSettings.user_id == item.user_id))
        user = await session.get(User, item.user_id)
        if not prefs or not prefs.email_enabled or not user:
            item.delivery_status = "SKIPPED"
            continue
        if in_quiet_hours(now, prefs):
            continue
        item.delivery_attempts += 1
        try:
            subject = str(item.payload.get("title") or item.notification_type.replace("_", " ").title())[:180]
            body = str(item.payload.get("message") or subject)[:4000]
            await asyncio.to_thread(_smtp_send, user.email, subject, body)
            item.delivery_status = "DELIVERED"
            item.delivered_at = now
            item.last_delivery_error = None
            item.next_attempt_at = None
            delivered += 1
        except Exception as exc:
            item.last_delivery_error = type(exc).__name__
            item.delivery_status = "FAILED" if item.delivery_attempts >= 5 else "PENDING"
            item.next_attempt_at = now + timedelta(seconds=min(30 * (2 ** (item.delivery_attempts - 1)), 600))
    await session.commit()
    return delivered
