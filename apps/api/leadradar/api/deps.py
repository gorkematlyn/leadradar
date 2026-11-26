"""Request-level security: sessions, CSRF, origin validation, rate limiting."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from leadradar.core.app_settings import get_setting
from leadradar.core.origins import HostValidationError, RequestOrigin, origin_matches, resolve_request_origin
from leadradar.core.security import constant_time_equals, hash_token
from leadradar.db.models import User, UserSession
from leadradar.db.session import get_db

SESSION_COOKIE = "lr_session"
CSRF_COOKIE = "lr_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def now() -> datetime:
    return datetime.now(UTC)


def _valid_ip(value: str | None) -> str | None:
    import ipaddress

    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request) -> str | None:
    """Best-effort client IP (validated); X-Forwarded-For only honoured from trusted proxies."""
    from leadradar.core.origins import is_trusted_proxy

    peer = _valid_ip(request.client.host if request.client else None)
    if is_trusted_proxy(peer):
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # Right-most untrusted address is the real client.
            for part in reversed([p.strip() for p in xff.split(",") if p.strip()]):
                if not is_trusted_proxy(part):
                    return _valid_ip(part)
        real = _valid_ip(request.headers.get("x-real-ip"))
        if real:
            return real
    return peer


def request_origin(request: Request, db: Session = Depends(get_db)) -> RequestOrigin:
    allowed = get_setting(db, "security.allowed_hosts") or []
    try:
        return resolve_request_origin({k.lower(): v for k, v in request.headers.items()},
                                      request.client.host if request.client else None, allowed)
    except HostValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid_host") from exc


@dataclass
class Principal:
    user: User
    session: UserSession


def _load_session(request: Request, db: Session, *, stage: str = "full") -> Principal | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) > 128:
        return None
    sess = db.query(UserSession).filter(UserSession.token_hash == hash_token(token)).one_or_none()
    if sess is None or sess.revoked_at is not None or sess.expires_at < now():
        return None
    idle = int(get_setting(db, "security.idle_timeout_minutes"))
    if sess.last_seen_at < now() - timedelta(minutes=idle):
        sess.revoked_at = now()
        return None
    if sess.stage != stage:
        return None
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        return None
    if now() - sess.last_seen_at > timedelta(minutes=1):
        sess.last_seen_at = now()
    return Principal(user, sess)


def verify_csrf(request: Request, db: Session, origin: RequestOrigin, sess: UserSession | None) -> None:
    """Origin check + double-submit token bound to the session (hash stored server-side)."""
    if request.method in SAFE_METHODS:
        return
    origin_header = request.headers.get("origin")
    if origin_header is not None:
        if not origin_matches(origin_header, origin):
            raise HTTPException(status_code=403, detail="csrf_origin")
    else:
        referer = request.headers.get("referer")
        if not referer or not origin_matches("/".join(referer.split("/")[:3]), origin):
            raise HTTPException(status_code=403, detail="csrf_origin")
    if sess is not None:
        header = request.headers.get(CSRF_HEADER, "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not header or not cookie or not constant_time_equals(header, cookie) or \
                not constant_time_equals(hash_token(header), sess.csrf_token_hash):
            raise HTTPException(status_code=403, detail="csrf_token")


def current_principal(request: Request, db: Session = Depends(get_db),
                      origin: RequestOrigin = Depends(request_origin)) -> Principal:
    p = _load_session(request, db)
    if p is None:
        raise HTTPException(status_code=401, detail="unauthenticated")
    verify_csrf(request, db, origin, p.session)
    request.state.user_id = p.user.id
    return p


def current_user(p: Principal = Depends(current_principal)) -> User:
    return p.user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="forbidden")
    return user


def rate_limit(db: Session, key: str, limit: int, window_seconds: int) -> bool:
    """Fixed-window counter in PostgreSQL. Returns True when allowed."""
    ts = now()
    window = ts - timedelta(seconds=ts.timestamp() % window_seconds)
    row = db.execute(text(
        "INSERT INTO rate_limit_buckets (key, window_start, count) VALUES (:k, :w, 1) "
        "ON CONFLICT (key, window_start) DO UPDATE SET count = rate_limit_buckets.count + 1 RETURNING count"),
        {"k": key[:200], "w": window}).scalar()
    if ts.second == 0 and ts.microsecond < 50_000:
        db.execute(text("DELETE FROM rate_limit_buckets WHERE window_start < :c"), {"c": ts - timedelta(hours=2)})
    return int(row or 0) <= limit


def parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="not_found") from exc
