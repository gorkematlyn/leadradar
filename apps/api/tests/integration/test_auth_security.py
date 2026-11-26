import pyotp
import pytest

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

pytestmark = pytest.mark.integration


def test_state_and_login_flow(client, admin_user):
    s = client.get("/api/auth/state").json()
    assert s["authenticated"] is False and s["setup_required"] is False
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    cookie_header = r.headers.get("set-cookie", "")
    assert "HttpOnly" in cookie_header and "Domain=" not in cookie_header and "SameSite=lax" in cookie_header
    assert client.get("/api/auth/state").json()["authenticated"] is True
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/companies/meta/cities").status_code == 401


def test_wrong_password_rejected(client, admin_user):
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "nope-nope-nope"})
    assert r.status_code == 401 and r.json()["detail"] == "invalid_credentials"
    r = client.post("/api/auth/login", json={"email": "unknown@example.test", "password": "nope-nope-nope"})
    assert r.status_code == 401 and r.json()["detail"] == "invalid_credentials"


@pytest.mark.parametrize("method,url", [
    ("get", "/api/dashboard"), ("post", "/api/companies/query"), ("get", "/api/jobs"), ("get", "/api/settings"),
    ("get", "/api/reports"), ("get", "/api/review-queue"), ("get", "/api/suppression"), ("get", "/api/health/system"),
])
def test_private_routes_require_auth(client, method, url):
    r = getattr(client, method)(url) if method == "get" else client.post(url, json={})
    assert r.status_code == 401


def test_csrf_token_and_origin_required(auth_client):
    c = auth_client.c
    r = c.post("/api/tags", json={"name": "x-no-csrf"}, headers={"Origin": "http://testserver"})
    assert r.status_code == 403 and r.json()["detail"] == "csrf_token"
    token = c.cookies.get("lr_csrf")
    r = c.post("/api/tags", json={"name": "x-bad-origin"}, headers={"Origin": "https://evil.example", "X-CSRF-Token": token})
    assert r.status_code == 403 and r.json()["detail"] == "csrf_origin"
    r = c.post("/api/tags", json={"name": "x-no-origin"}, headers={"X-CSRF-Token": token})
    assert r.status_code == 403
    assert auth_client.post("/api/tags", json={"name": "csrf-ok"}).status_code == 200


def test_host_header_injection_rejected_with_allowlist(auth_client):
    assert auth_client.put("/api/settings", json={"values": {"security.allowed_hosts": ["testserver"]}}).status_code == 200
    r = auth_client.c.get("/api/dashboard", headers={"Host": "evil.example"})
    assert r.status_code == 400 and r.json()["detail"] == "invalid_host"
    assert auth_client.get("/api/dashboard").status_code == 200
    assert auth_client.put("/api/settings", json={"values": {"security.allowed_hosts": []}}).status_code == 200


def test_security_headers_and_no_docs(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "noindex" in r.headers["x-robots-tag"]
    assert r.headers["x-frame-options"] == "DENY"
    for path in ("/docs", "/redoc", "/openapi.json", "/api/docs", "/api/openapi.json"):
        assert client.get(path).status_code == 404


def test_totp_enrollment_and_mfa_login(client, migrated_db):
    from leadradar.core.security import hash_password
    from leadradar.db.models import User
    from leadradar.db.session import session_scope

    with session_scope() as s:
        s.add(User(email="mfa@example.test", display_name="MFA", password_hash=hash_password("mfa-password-123456")))
    assert client.post("/api/auth/login", json={"email": "mfa@example.test", "password": "mfa-password-123456"}).status_code == 200
    setup = client.post("/api/auth/totp/setup").json()
    totp = pyotp.TOTP(setup["secret"])
    codes = client.post("/api/auth/totp/enable", json={"code": totp.now()}).json()["recovery_codes"]
    assert len(codes) == 10
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"email": "mfa@example.test", "password": "mfa-password-123456"})
    assert r.json() == {"mfa_required": True}
    assert client.get("/api/dashboard").status_code == 401  # pending MFA session grants nothing
    assert client.post("/api/auth/mfa", json={"code": "000000"}).status_code == 401
    r = client.post("/api/auth/mfa", json={"recovery_code": codes[0]})
    assert r.status_code == 200
    assert client.get("/api/dashboard").status_code == 200
    # recovery codes are single use
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "mfa@example.test", "password": "mfa-password-123456"})
    assert client.post("/api/auth/mfa", json={"recovery_code": codes[0]}).status_code == 401


def test_account_lockout(client, migrated_db):
    from leadradar.core.security import hash_password
    from leadradar.db.models import User
    from leadradar.db.session import session_scope

    with session_scope() as s:
        s.add(User(email="lock@example.test", display_name="L", password_hash=hash_password("lock-password-123456")))
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "lock@example.test", "password": "wrong-password-x"})
    r = client.post("/api/auth/login", json={"email": "lock@example.test", "password": "lock-password-123456"})
    assert r.status_code == 429 and r.json()["detail"] == "account_locked"


def test_logout_all_revokes_sessions(auth_client):
    assert len(auth_client.get("/api/auth/sessions").json()) >= 1
    assert auth_client.post("/api/auth/logout-all").status_code == 200
    assert auth_client.get("/api/dashboard").status_code == 401


def test_session_idle_timeout(auth_client, migrated_db):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from leadradar.db.models import UserSession
    from leadradar.db.session import session_scope

    with session_scope() as s:
        s.execute(update(UserSession).where(UserSession.revoked_at.is_(None))
                  .values(last_seen_at=datetime.now(UTC) - timedelta(days=1)))
    assert auth_client.get("/api/dashboard").status_code == 401
