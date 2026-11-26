"""Test configuration.

Unit tests need no database. Integration tests require ``TEST_DATABASE_URL`` pointing at
a disposable PostgreSQL database; the schema is dropped and recreated once per session.
"""

from __future__ import annotations

import base64
import os

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
os.environ.setdefault("APP_ENV", "test")
os.environ["APP_ENV"] = "test"
os.environ.setdefault("SESSION_SECRET", "test-session-secret-0123456789-abcdefghijklmnop")
os.environ.setdefault("APP_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"k" * 32).decode())
os.environ["DATABASE_URL"] = TEST_DB or "postgresql://invalid@127.0.0.1:1/none"
os.environ.setdefault("WORKER_TMP_DIR", "/tmp/leadradar-test")  # noqa: S108


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    if TEST_DB:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def migrated_db():  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    from leadradar.db.session import get_engine, session_scope
    from leadradar.seeds.run import run_seed

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    from alembic import command
    from alembic.config import Config

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "migrations"))
    command.upgrade(cfg, "head")
    with session_scope() as db:
        run_seed(db)
    return engine


@pytest.fixture
def db(migrated_db):  # type: ignore[no-untyped-def]
    from leadradar.db.session import get_sessionmaker

    s = get_sessionmaker()()
    yield s
    s.rollback()
    s.close()


ADMIN_EMAIL = "admin@example.test"
ADMIN_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(scope="session")
def admin_user(migrated_db):  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from leadradar.core.security import hash_password
    from leadradar.db.models import User, UserPreference
    from leadradar.db.session import session_scope

    with session_scope() as s:
        u = s.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if u is None:
            u = User(email=ADMIN_EMAIL, display_name="Admin", password_hash=hash_password(ADMIN_PASSWORD))
            s.add(u)
            s.flush()
            s.add(UserPreference(user_id=u.id))
        return u.id


ORIGIN = "http://testserver"


class ApiClient:
    def __init__(self, client):  # type: ignore[no-untyped-def]
        self.c = client

    def _h(self, extra=None):  # type: ignore[no-untyped-def]
        h = {"Origin": ORIGIN}
        csrf = self.c.cookies.get("lr_csrf")
        if csrf:
            h["X-CSRF-Token"] = csrf
        h.update(extra or {})
        return h

    def get(self, url, **kw):  # type: ignore[no-untyped-def]
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):  # type: ignore[no-untyped-def]
        return self.c.post(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def patch(self, url, json=None, **kw):  # type: ignore[no-untyped-def]
        return self.c.patch(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def put(self, url, json=None, **kw):  # type: ignore[no-untyped-def]
        return self.c.put(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def delete(self, url, **kw):  # type: ignore[no-untyped-def]
        return self.c.delete(url, headers=self._h(kw.pop("headers", None)), **kw)


@pytest.fixture
def client(migrated_db):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from leadradar.main import app

    with TestClient(app, base_url=ORIGIN) as c:
        yield ApiClient(c)


@pytest.fixture
def auth_client(client, admin_user):  # type: ignore[no-untyped-def]
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return client
