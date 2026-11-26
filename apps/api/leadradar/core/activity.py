from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from leadradar.db.models import ActivityLog


def record_activity(
    db: Session,
    category: str,
    action: str,
    *,
    user_id: Any = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        ActivityLog(
            user_id=user_id, category=category, action=action, entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None, details=details or {},
            ip_address=ip, created_at=datetime.now(UTC),
        )
    )
