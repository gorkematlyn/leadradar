"""Report lifecycle: drafts, approval, publication tokens, revocation, PDF generation."""

from __future__ import annotations

import base64
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from leadradar.core.security import generate_token, hash_password, hash_token
from leadradar.db.models import (
    EvidenceBlob,
    Report,
    ReportAccessToken,
    ReportAsset,
    ReportVersion,
)
from leadradar.db.session import session_scope
from leadradar.jobs import queue
from leadradar.jobs.runtime import HandlerResult, JobContext, PermanentJobError, handler


def now() -> datetime:
    return datetime.now(UTC)


def approve_version(db: Session, report: Report, version: ReportVersion, user_id: uuid.UUID | None) -> None:
    """Approval makes a version eligible for public display (live reports switch to it)."""
    if version.report_id != report.id:
        raise ValueError("version does not belong to report")
    version.status = "approved"
    version.approved_at = now()
    version.approved_by = user_id
    report.published_version_id = version.id
    for asset in db.scalars(select(ReportAsset).where(ReportAsset.report_version_id == version.id)):
        blob = db.get(EvidenceBlob, asset.blob_id)
        if blob:
            blob.pinned = True  # evidence required by a published report is retained
    db.flush()
    for lang in ("en", "tr"):
        queue.enqueue(db, "report_pdf", f"Report PDF v{version.version} ({lang})",
                      {"version_id": str(version.id), "lang": lang},
                      idempotency_key=f"report_pdf:{version.id}:{lang}")


def publish(db: Session, report: Report, *, expires_at: datetime | None, password: str | None,
            allow_pdf: bool = True) -> tuple[ReportAccessToken, str]:
    """Create a new unguessable public link. Requires an approved version."""
    if report.published_version_id is None:
        raise ValueError("approve a report version before publishing")
    token = generate_token(32)
    pinned = report.published_version_id if report.mode == "snapshot" else None
    row = ReportAccessToken(report_id=report.id, token_hash=hash_token(token), token_hint=token[:6],
                            pinned_version_id=pinned, expires_at=expires_at,
                            password_hash=hash_password(password) if password else None, allow_pdf=allow_pdf)
    db.add(row)
    report.status = "published"
    db.flush()
    return row, token


def revoke(db: Session, token_row: ReportAccessToken) -> None:
    token_row.revoked_at = now()
    db.flush()


def rotate(db: Session, token_row: ReportAccessToken) -> tuple[ReportAccessToken, str]:
    report = db.get(Report, token_row.report_id)
    assert report is not None
    revoke(db, token_row)
    new_token = generate_token(32)
    row = ReportAccessToken(report_id=report.id, token_hash=hash_token(new_token), token_hint=new_token[:6],
                            pinned_version_id=token_row.pinned_version_id, expires_at=token_row.expires_at,
                            password_hash=token_row.password_hash, allow_pdf=token_row.allow_pdf)
    db.add(row)
    db.flush()
    return row, new_token


def revoke_all(db: Session, report: Report) -> None:
    db.execute(update(ReportAccessToken).where(ReportAccessToken.report_id == report.id,
                                               ReportAccessToken.revoked_at.is_(None)).values(revoked_at=now()))
    report.status = "revoked"


def resolve_token(db: Session, token: str) -> tuple[ReportAccessToken, Report, ReportVersion] | None:
    """Return the token, report and visible version, or None (uniform for all failure modes)."""
    if not token or len(token) > 100:
        return None
    row = db.scalar(select(ReportAccessToken).where(ReportAccessToken.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None or (row.expires_at and row.expires_at < now()):
        return None
    report = db.get(Report, row.report_id)
    if report is None or report.status != "published":
        return None
    version_id = row.pinned_version_id or report.published_version_id
    version = db.get(ReportVersion, version_id) if version_id else None
    if version is None or version.status != "approved":
        return None
    return row, report, version


def blob_data_uri(db: Session, blob_id: uuid.UUID) -> str:
    blob = db.get(EvidenceBlob, blob_id)
    if blob is None:
        return ""
    return f"data:{blob.content_type};base64,{base64.b64encode(blob.data).decode()}"


@handler("report_pdf")
def handle_pdf(ctx: JobContext) -> HandlerResult:
    """Render the approved version with the print stylesheet and store an A4 PDF."""
    from leadradar.modules.reporting.render import render_report

    version_id = uuid.UUID(ctx.payload["version_id"])
    lang = ctx.payload.get("lang", "en")
    with session_scope() as db:
        version = db.get(ReportVersion, version_id)
        if version is None or version.status != "approved":
            raise PermanentJobError("version not approved")
        assets = {a.public_id: a.blob_id for a in db.scalars(select(ReportAsset).where(
            ReportAsset.report_version_id == version.id, ReportAsset.kind == "screenshot"))}
        uris = {pid: blob_data_uri(db, bid) for pid, bid in assets.items()}
        html = render_report(version.content, version=version.version, lang=lang, asset_url=lambda p: uris.get(p, ""),
                             pdf_url=None, print_mode=True, nonce=secrets.token_urlsafe(8))
        title = version.content.get("title", "Report")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        try:
            context = browser.new_context(java_script_enabled=False, accept_downloads=False)
            page = context.new_page()
            # The document is self-contained (fonts and images as data URIs); block every network request.
            page.route("**/*", lambda route: route.abort() if not route.request.url.startswith("data:") else route.continue_())
            page.set_content(html, wait_until="load", timeout=30_000)
            footer = ('<div style="font-size:8px;width:100%;padding:0 16mm;color:#777;display:flex;justify-content:space-between;">'
                      f'<span>{_escape(title)}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')
            pdf = page.pdf(format="A4", print_background=True, display_header_footer=True,
                           header_template="<span></span>", footer_template=footer,
                           margin={"top": "16mm", "bottom": "18mm", "left": "0", "right": "0"})
        finally:
            browser.close()
    with session_scope() as db:
        old = db.scalars(select(ReportAsset).where(ReportAsset.report_version_id == version_id,
                                                   ReportAsset.kind == "pdf", ReportAsset.language == lang)).all()
        for a in old:
            db.delete(a)
        import hashlib

        blob = EvidenceBlob(content_type="application/pdf", size_bytes=len(pdf), sha256=hashlib.sha256(pdf).hexdigest(),
                            data=pdf, created_at=now(), pinned=True)
        db.add(blob)
        db.flush()
        db.add(ReportAsset(report_version_id=version_id, kind="pdf", language=lang, public_id=secrets.token_urlsafe(18),
                           blob_id=blob.id, created_at=now()))
    return HandlerResult({"bytes": len(pdf), "lang": lang})


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def expires_in(days: int | None) -> datetime | None:
    return now() + timedelta(days=days) if days else None
