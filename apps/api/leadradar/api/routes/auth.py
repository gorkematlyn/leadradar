from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import pyotp
import segno
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from leadradar.api.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    Principal,
    _load_session,
    client_ip,
    current_principal,
    rate_limit,
    request_origin,
    verify_csrf,
)
from leadradar.core.activity import record_activity
from leadradar.core.app_settings import get_setting
from leadradar.core.config import get_settings
from leadradar.core.origins import RequestOrigin
from leadradar.core.security import (
    decrypt_secret,
    dummy_verify,
    encrypt_secret,
    generate_recovery_codes,
    generate_token,
    hash_password,
    hash_token,
    normalize_recovery_code,
    password_needs_rehash,
    validate_password_strength,
    verify_password,
)
from leadradar.db.models import LoginAttempt, RecoveryCode, User, UserPreference, UserSession
from leadradar.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def now() -> datetime:
    return datetime.now(UTC)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=1, max_length=256)


class MfaIn(BaseModel):
    code: str | None = Field(default=None, max_length=12)
    recovery_code: str | None = Field(default=None, max_length=20)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class TotpCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class TotpDisableIn(BaseModel):
    password: str = Field(max_length=256)
    code: str = Field(min_length=6, max_length=20)


def _set_cookies(response: Response, origin: RequestOrigin, token: str, csrf: str, max_age: int) -> None:
    secure = origin.scheme == "https" or get_settings().is_production
    # Host-only cookies (no Domain attribute) so a domain change needs no configuration.
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=secure, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=secure, samesite="lax", path="/")


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _new_session(db: Session, user: User, request: Request, stage: str) -> tuple[str, str, int]:
    token, csrf = generate_token(32), generate_token(24)
    ttl_h = int(get_setting(db, "security.session_ttl_hours"))
    max_age = 300 if stage == "mfa_pending" else ttl_h * 3600
    db.add(UserSession(user_id=user.id, token_hash=hash_token(token), csrf_token_hash=hash_token(csrf), stage=stage,
                       expires_at=now() + timedelta(seconds=max_age), last_seen_at=now(), ip_address=client_ip(request),
                       user_agent=(request.headers.get("user-agent") or "")[:400]))
    db.flush()
    return token, csrf, max_age


def _user_view(user: User, db: Session) -> dict:
    pref = db.get(UserPreference, user.id)
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name, "role": user.role,
            "totp_enabled": user.totp_enabled, "locale": pref.locale if pref else "en",
            "theme": pref.theme if pref else "system",
            "table_preferences": pref.table_preferences if pref else {},
            "sidebar_collapsed": pref.sidebar_collapsed if pref else False}


@router.get("/state")
def auth_state(request: Request, db: Session = Depends(get_db)) -> dict:
    has_users = bool(db.scalar(select(func.count()).select_from(User)))
    p = _load_session(request, db)
    pending = _load_session(request, db, stage="mfa_pending") if p is None else None
    return {"setup_required": not has_users, "authenticated": p is not None, "mfa_pending": pending is not None,
            "user": _user_view(p.user, db) if p else None}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db),
          origin: RequestOrigin = Depends(request_origin)) -> dict:
    verify_csrf(request, db, origin, None)
    ip = client_ip(request)
    email = body.email.lower()
    if not rate_limit(db, f"login:ip:{ip or 'unknown'}", 20, 900):
        raise HTTPException(429, "too_many_attempts")
    max_attempts = int(get_setting(db, "security.login_max_attempts"))
    lockout = int(get_setting(db, "security.login_lockout_minutes"))
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        dummy_verify()
        db.add(LoginAttempt(key=f"email:{email}", success=False, attempted_at=now()))
        db.commit()
        raise HTTPException(401, "invalid_credentials")
    if user.locked_until and user.locked_until > now():
        dummy_verify()
        raise HTTPException(429, "account_locked")
    if not user.is_active or not verify_password(user.password_hash, body.password):
        user.failed_login_count += 1
        if user.failed_login_count >= max_attempts:
            user.locked_until = now() + timedelta(minutes=lockout)
            user.failed_login_count = 0
            record_activity(db, "security", "account_locked", user_id=user.id, ip=ip)
        db.add(LoginAttempt(key=f"email:{email}", success=False, attempted_at=now()))
        record_activity(db, "security", "login_failed", user_id=user.id, ip=ip)
        db.commit()
        raise HTTPException(401, "invalid_credentials")
    user.failed_login_count = 0
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    stage = "mfa_pending" if user.totp_enabled else "full"
    token, csrf, max_age = _new_session(db, user, request, stage)
    _set_cookies(response, origin, token, csrf, max_age)
    if stage == "full":
        user.last_login_at = now()
        record_activity(db, "security", "login", user_id=user.id, ip=ip)
        return {"mfa_required": False, "user": _user_view(user, db)}
    return {"mfa_required": True}


@router.post("/mfa")
def mfa(body: MfaIn, request: Request, response: Response, db: Session = Depends(get_db),
        origin: RequestOrigin = Depends(request_origin)) -> dict:
    pending = _load_session(request, db, stage="mfa_pending")
    if pending is None:
        raise HTTPException(401, "unauthenticated")
    verify_csrf(request, db, origin, pending.session)
    ip = client_ip(request)
    if not rate_limit(db, f"mfa:{pending.user.id}", 8, 300):
        raise HTTPException(429, "too_many_attempts")
    user = pending.user
    ok = False
    if body.code and user.totp_secret_enc:
        totp = pyotp.TOTP(decrypt_secret(user.totp_secret_enc))
        code = body.code.strip().replace(" ", "")
        for offset in (-1, 0, 1):
            counter = int(now().timestamp() // 30) + offset
            if pyotp.utils.strings_equal(totp.at(counter * 30), code) and (user.totp_last_counter or 0) < counter:
                user.totp_last_counter = counter  # prevent code replay
                ok = True
                break
    elif body.recovery_code:
        rc = normalize_recovery_code(body.recovery_code)
        for row in db.scalars(select(RecoveryCode).where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))):
            if verify_password(row.code_hash, rc):
                row.used_at = now()
                ok = True
                record_activity(db, "security", "recovery_code_used", user_id=user.id, ip=ip)
                break
    if not ok:
        record_activity(db, "security", "mfa_failed", user_id=user.id, ip=ip)
        db.commit()
        raise HTTPException(401, "invalid_code")
    pending.session.revoked_at = now()
    token, csrf, max_age = _new_session(db, user, request, "full")
    _set_cookies(response, origin, token, csrf, max_age)
    user.last_login_at = now()
    record_activity(db, "security", "login", user_id=user.id, ip=ip, details={"mfa": True})
    return {"user": _user_view(user, db)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db),
           origin: RequestOrigin = Depends(request_origin)) -> dict:
    p = _load_session(request, db) or _load_session(request, db, stage="mfa_pending")
    if p is not None:
        verify_csrf(request, db, origin, p.session)
        p.session.revoked_at = now()
        record_activity(db, "security", "logout", user_id=p.user.id, ip=client_ip(request))
    _clear_cookies(response)
    return {"ok": True}


@router.post("/logout-all")
def logout_all(request: Request, response: Response, p: Principal = Depends(current_principal),
               db: Session = Depends(get_db)) -> dict:
    db.execute(update(UserSession).where(UserSession.user_id == p.user.id, UserSession.revoked_at.is_(None))
               .values(revoked_at=now()))
    record_activity(db, "security", "logout_all", user_id=p.user.id, ip=client_ip(request))
    _clear_cookies(response)
    return {"ok": True}


@router.get("/sessions")
def sessions(p: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(UserSession).where(UserSession.user_id == p.user.id, UserSession.revoked_at.is_(None),
                                                UserSession.expires_at > now(), UserSession.stage == "full")
                      .order_by(UserSession.last_seen_at.desc())).all()
    return [{"id": str(s.id), "created_at": s.created_at, "last_seen_at": s.last_seen_at, "ip": str(s.ip_address or ""),
             "user_agent": s.user_agent, "current": s.id == p.session.id} for s in rows]


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: uuid.UUID, request: Request, p: Principal = Depends(current_principal),
                   db: Session = Depends(get_db)) -> dict:
    s = db.get(UserSession, session_id)
    if s is None or s.user_id != p.user.id:
        raise HTTPException(404, "not_found")
    s.revoked_at = now()
    record_activity(db, "security", "session_revoked", user_id=p.user.id, ip=client_ip(request))
    return {"ok": True}


@router.post("/password")
def change_password(body: PasswordIn, request: Request, response: Response, p: Principal = Depends(current_principal),
                    db: Session = Depends(get_db), origin: RequestOrigin = Depends(request_origin)) -> dict:
    if not rate_limit(db, f"pwchange:{p.user.id}", 5, 900):
        raise HTTPException(429, "too_many_attempts")
    if not verify_password(p.user.password_hash, body.current_password):
        raise HTTPException(400, "invalid_current_password")
    problems = validate_password_strength(body.new_password)
    if problems:
        raise HTTPException(400, problems[0])
    p.user.password_hash = hash_password(body.new_password)
    p.user.password_changed_at = now()
    # Revoke every other session; keep the current one alive with a fresh token.
    db.execute(update(UserSession).where(UserSession.user_id == p.user.id, UserSession.revoked_at.is_(None))
               .values(revoked_at=now()))
    token, csrf, max_age = _new_session(db, p.user, request, "full")
    _set_cookies(response, origin, token, csrf, max_age)
    record_activity(db, "security", "password_changed", user_id=p.user.id, ip=client_ip(request))
    return {"ok": True}


@router.post("/totp/setup")
def totp_setup(p: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> dict:
    if p.user.totp_enabled:
        raise HTTPException(400, "totp_already_enabled")
    secret = pyotp.random_base32()
    p.user.totp_pending_secret_enc = encrypt_secret(secret)
    uri = pyotp.TOTP(secret).provisioning_uri(name=p.user.email, issuer_name="LeadRadar")
    buf = io.BytesIO()
    segno.make(uri, error="m").save(buf, kind="svg", scale=4, border=2, dark="#101210", light="#ffffff")
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": buf.getvalue().decode()}


@router.post("/totp/enable")
def totp_enable(body: TotpCodeIn, request: Request, p: Principal = Depends(current_principal),
                db: Session = Depends(get_db)) -> dict:
    if not p.user.totp_pending_secret_enc:
        raise HTTPException(400, "totp_not_started")
    secret = decrypt_secret(p.user.totp_pending_secret_enc)
    if not pyotp.TOTP(secret).verify(body.code.strip(), valid_window=1):
        raise HTTPException(400, "invalid_code")
    p.user.totp_secret_enc = encrypt_secret(secret)
    p.user.totp_pending_secret_enc = None
    p.user.totp_enabled = True
    codes = _replace_recovery_codes(db, p.user)
    record_activity(db, "security", "totp_enabled", user_id=p.user.id, ip=client_ip(request))
    return {"recovery_codes": codes}


@router.post("/totp/disable")
def totp_disable(body: TotpDisableIn, request: Request, p: Principal = Depends(current_principal),
                 db: Session = Depends(get_db)) -> dict:
    if not verify_password(p.user.password_hash, body.password):
        raise HTTPException(400, "invalid_current_password")
    secret = decrypt_secret(p.user.totp_secret_enc) if p.user.totp_secret_enc else None
    if not secret or not pyotp.TOTP(secret).verify(body.code.strip(), valid_window=1):
        raise HTTPException(400, "invalid_code")
    p.user.totp_enabled = False
    p.user.totp_secret_enc = None
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == p.user.id))
    record_activity(db, "security", "totp_disabled", user_id=p.user.id, ip=client_ip(request))
    return {"ok": True}


@router.post("/recovery-codes")
def regenerate_codes(body: TotpCodeIn, request: Request, p: Principal = Depends(current_principal),
                     db: Session = Depends(get_db)) -> dict:
    secret = decrypt_secret(p.user.totp_secret_enc) if p.user.totp_secret_enc else None
    if not secret or not pyotp.TOTP(secret).verify(body.code.strip(), valid_window=1):
        raise HTTPException(400, "invalid_code")
    codes = _replace_recovery_codes(db, p.user)
    record_activity(db, "security", "recovery_codes_regenerated", user_id=p.user.id, ip=client_ip(request))
    return {"recovery_codes": codes}


def _replace_recovery_codes(db: Session, user: User) -> list[str]:
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = generate_recovery_codes()
    for c in codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=hash_password(normalize_recovery_code(c))))
    return codes


class PreferencesIn(BaseModel):
    locale: str | None = Field(default=None, pattern="^(en|tr)$")
    theme: str | None = Field(default=None, pattern="^(light|dark|system)$")
    table_preferences: dict | None = None
    sidebar_collapsed: bool | None = None
    display_name: str | None = Field(default=None, max_length=200)


@router.put("/preferences")
def update_preferences(body: PreferencesIn, p: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> dict:
    pref = db.get(UserPreference, p.user.id)
    if pref is None:
        pref = UserPreference(user_id=p.user.id)
        db.add(pref)
    if body.locale:
        pref.locale = body.locale
    if body.theme:
        pref.theme = body.theme
    if body.table_preferences is not None:
        if len(str(body.table_preferences)) > 20_000:
            raise HTTPException(400, "too_large")
        pref.table_preferences = body.table_preferences
    if body.sidebar_collapsed is not None:
        pref.sidebar_collapsed = body.sidebar_collapsed
    if body.display_name:
        p.user.display_name = body.display_name
    db.flush()
    return _user_view(p.user, db)
