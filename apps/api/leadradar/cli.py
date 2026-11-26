"""Command-line entry points.

    leadradar migrate            apply migrations (advisory-locked) and run idempotent seeds
    leadradar create-admin       create the first administrator (interactive or --email/--password-stdin)
    leadradar reset-mfa EMAIL    disable 2FA for an account (recovery)
    leadradar serve              start the API (uvicorn)
    leadradar worker QUEUES      start a worker (discovery | analysis)
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from leadradar.core.config import get_settings
from leadradar.core.logging import configure_logging


def cmd_migrate(_: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from leadradar.db.session import get_engine, session_scope
    from leadradar.seeds.run import run_seed

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "migrations"))
    engine = get_engine()
    # Session-level advisory lock: only one container migrates at a time.
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(hashtext('leadradar.migrate'))"))
        try:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            conn.commit()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(hashtext('leadradar.migrate'))"))
            conn.commit()
    with session_scope() as db:
        run_seed(db)
    from leadradar.jobs.scheduler import schedule_initial_import

    with session_scope() as db:
        schedule_initial_import(db)
    print("migrations and seeds applied")
    return 0


def cmd_create_admin(args: argparse.Namespace) -> int:
    from sqlalchemy import func, select

    from leadradar.core.activity import record_activity
    from leadradar.core.security import hash_password, validate_password_strength
    from leadradar.db.models import User, UserPreference
    from leadradar.db.session import session_scope

    email = (args.email or input("Administrator email: ")).strip().lower()
    if "@" not in email:
        print("invalid email", file=sys.stderr)
        return 2
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password (min 12 chars): ")
        if password != getpass.getpass("Repeat password: "):
            print("passwords do not match", file=sys.stderr)
            return 2
    problems = validate_password_strength(password)
    if problems:
        print("weak password: " + ", ".join(problems), file=sys.stderr)
        return 2
    with session_scope() as db:
        if db.scalar(select(func.count()).select_from(User).where(func.lower(User.email) == email)):
            print("an account with this email already exists", file=sys.stderr)
            return 1
        existing = db.scalar(select(func.count()).select_from(User))
        if existing and not args.additional:
            print("an administrator already exists; pass --additional to add another", file=sys.stderr)
            return 1
        from datetime import UTC, datetime

        user = User(email=email, display_name=args.name or email.split("@")[0], password_hash=hash_password(password),
                    password_changed_at=datetime.now(UTC))
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id, locale=args.locale, theme="system"))
        record_activity(db, "security", "admin_created", user_id=user.id, details={"via": "cli"})
    print(f"administrator {email} created")
    return 0


def cmd_reset_mfa(args: argparse.Namespace) -> int:
    from sqlalchemy import delete, select, update

    from leadradar.core.activity import record_activity
    from leadradar.db.models import RecoveryCode, User, UserSession
    from leadradar.db.session import session_scope

    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == args.email.lower()))
        if not user:
            print("no such user", file=sys.stderr)
            return 1
        user.totp_enabled = False
        user.totp_secret_enc = None
        db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        from datetime import UTC, datetime

        db.execute(update(UserSession).where(UserSession.user_id == user.id).values(revoked_at=datetime.now(UTC)))
        record_activity(db, "security", "mfa_reset", user_id=user.id, details={"via": "cli"})
    print("2FA disabled and sessions revoked")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "leadradar.main:app", host=args.host, port=args.port, workers=args.workers, proxy_headers=False,
        server_header=False, date_header=False, log_config=None, timeout_graceful_shutdown=20,
    )
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    from leadradar.workers.main import run_worker

    run_worker(args.queues.split(","), args.concurrency)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="leadradar")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    p = sub.add_parser("create-admin")
    p.add_argument("--email")
    p.add_argument("--name")
    p.add_argument("--locale", default="en", choices=["en", "tr"])
    p.add_argument("--password-stdin", action="store_true")
    p.add_argument("--additional", action="store_true")
    p.set_defaults(fn=cmd_create_admin)
    p = sub.add_parser("reset-mfa")
    p.add_argument("email")
    p.set_defaults(fn=cmd_reset_mfa)
    p = sub.add_parser("serve")
    p.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container interface
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--workers", type=int, default=1)
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("worker")
    p.add_argument("queues", nargs="?", default=None)
    p.add_argument("--concurrency", type=int, default=None)
    p.set_defaults(fn=cmd_worker)
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    if args.cmd == "worker":
        args.queues = args.queues or settings.worker_queues
        args.concurrency = args.concurrency or settings.worker_concurrency
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
