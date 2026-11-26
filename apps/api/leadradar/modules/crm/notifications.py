"""Persistent in-app notifications (no external services)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from leadradar.db.models import Notification


def notify(
    db: Session,
    kind: str,
    message_key: str,
    params: dict[str, Any] | None = None,
    *,
    severity: str = "info",
    link: str | None = None,
    dedupe_key: str | None = None,
    dedupe_hours: int = 24,
    user_id: Any = None,
) -> Notification | None:
    """Create a notification. ``dedupe_key`` suppresses repeats within ``dedupe_hours``."""
    if dedupe_key:
        since = datetime.now(UTC) - timedelta(hours=dedupe_hours)
        exists = db.scalar(
            select(Notification.id).where(Notification.dedupe_key == dedupe_key, Notification.created_at >= since)
        )
        if exists:
            return None
    n = Notification(
        kind=kind, message_key=message_key, params=params or {}, severity=severity, link=link,
        dedupe_key=dedupe_key, created_at=datetime.now(UTC), user_id=user_id,
    )
    db.add(n)
    db.flush()
    return n
