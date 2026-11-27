from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from leadradar.api.deps import client_ip, current_user, rate_limit, request_origin
from leadradar.api.routes.companies import get_company
from leadradar.core.activity import record_activity
from leadradar.core.app_settings import get_setting
from leadradar.core.config import get_settings
from leadradar.core.origins import RequestOrigin
from leadradar.core.security import verify_password
from leadradar.db.models import (
    Company,
    EvidenceBlob,
    Report,
    ReportAccessToken,
    ReportAsset,
    ReportTemplate,
    ReportVersion,
    User,
)
from leadradar.db.session import get_db
from leadradar.modules.reporting import service as rs
from leadradar.modules.reporting.builder import SECTIONS, create_version
from leadradar.modules.reporting.render import render_message, render_report

router = APIRouter(tags=["reports"])
public = APIRouter(prefix="/r", tags=["public"])


def report_view(db: Session, r: Report) -> dict:
    company = db.get(Company, r.company_id)
    versions = db.scalars(select(ReportVersion).where(ReportVersion.report_id == r.id)
                          .order_by(ReportVersion.version.desc())).all()
    tokens = db.scalars(select(ReportAccessToken).where(ReportAccessToken.report_id == r.id)
                        .order_by(ReportAccessToken.created_at.desc())).all()
    pdfs = {(a.report_version_id, a.language) for a in db.scalars(select(ReportAsset).where(
        ReportAsset.kind == "pdf", ReportAsset.report_version_id.in_([v.id for v in versions])))} if versions else set()
    return {
        "id": str(r.id), "title": r.title, "mode": r.mode, "language": r.language, "sections": r.sections,
        "status": r.status, "company": {"id": str(company.id), "name": company.name} if company else None,
        "selected_evidence_ids": [str(x) for x in r.selected_evidence_ids], "selected_ad_ids": [str(x) for x in r.selected_ad_ids],
        "public_notes": r.public_notes, "branding": r.branding, "created_at": r.created_at, "updated_at": r.updated_at,
        "published_version_id": str(r.published_version_id) if r.published_version_id else None,
        "versions": [{"id": str(v.id), "version": v.version, "status": v.status, "created_at": v.created_at,
                      "approved_at": v.approved_at, "pdf": {"en": (v.id, "en") in pdfs, "tr": (v.id, "tr") in pdfs}}
                     for v in versions],
        "links": [{"id": str(t.id), "hint": t.token_hint, "pinned_version_id": str(t.pinned_version_id) if t.pinned_version_id else None,
                   "expires_at": t.expires_at, "revoked_at": t.revoked_at, "password_protected": bool(t.password_hash),
                   "view_count": t.view_count, "last_viewed_at": t.last_viewed_at, "allow_pdf": t.allow_pdf,
                   "created_at": t.created_at} for t in tokens],
    }


@router.get("/reports")
def list_reports(db: Session = Depends(get_db), _: User = Depends(current_user), company_id: uuid.UUID | None = None) -> list[dict]:
    q = (select(Report).join(Company, Company.id == Report.company_id).where(Company.deleted_at.is_(None))
         .order_by(Report.updated_at.desc()).limit(300))
    if company_id:
        q = q.where(Report.company_id == company_id)
    return [report_view(db, r) for r in db.scalars(q)]


@router.get("/report-templates")
def templates(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    return [{"id": str(t.id), "key": t.key, "name_en": t.name_en, "name_tr": t.name_tr,
             "default_sections": t.default_sections, "is_default": t.is_default}
            for t in db.scalars(select(ReportTemplate))]


class ReportIn(BaseModel):
    company_id: uuid.UUID
    template_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    mode: Literal["live", "snapshot"] = "snapshot"
    language: Literal["en", "tr"] = "en"
    sections: list[str] | None = None


@router.post("/reports")
def create_report(body: ReportIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    company = get_company(db, body.company_id)
    tpl = db.get(ReportTemplate, body.template_id) if body.template_id else db.scalar(
        select(ReportTemplate).where(ReportTemplate.is_default.is_(True)))
    sections = [s for s in (body.sections or (tpl.default_sections if tpl else SECTIONS)) if s in SECTIONS]
    r = Report(company_id=company.id, template_id=tpl.id if tpl else None, title=body.title, mode=body.mode,
               language=body.language, sections=sections, created_by=user.id,
               branding={"name": get_setting(db, "report.branding_name"), "contact": get_setting(db, "report.branding_contact")})
    db.add(r)
    db.flush()
    create_version(db, r)
    return report_view(db, r)


@router.get("/reports/{report_id}")
def get_report(report_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "not_found")
    return report_view(db, r)


class ReportPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    mode: Literal["live", "snapshot"] | None = None
    language: Literal["en", "tr"] | None = None
    sections: list[str] | None = None
    selected_evidence_ids: list[uuid.UUID] | None = None
    selected_ad_ids: list[uuid.UUID] | None = None
    public_notes: str | None = Field(default=None, max_length=5000)
    branding: dict[str, str] | None = None


@router.patch("/reports/{report_id}")
def patch_report(report_id: uuid.UUID, body: ReportPatch, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "not_found")
    data = body.model_dump(exclude_unset=True)
    if "sections" in data:
        data["sections"] = [s for s in data["sections"] or [] if s in SECTIONS]
    if "branding" in data:
        data["branding"] = {k: str(v)[:200] for k, v in (data["branding"] or {}).items() if k in ("name", "contact", "accent")}
    for k, v in data.items():
        setattr(r, k, v)
    return report_view(db, r)


@router.post("/reports/{report_id}/versions")
def new_version(report_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "not_found")
    v = create_version(db, r)
    return {"id": str(v.id), "version": v.version}


@router.get("/reports/{report_id}/versions/{version_id}/preview", response_class=HTMLResponse)
def preview(report_id: uuid.UUID, version_id: uuid.UUID, request: Request, lang: str = "en",
            db: Session = Depends(get_db), _: User = Depends(current_user)) -> HTMLResponse:
    v = db.get(ReportVersion, version_id)
    if v is None or v.report_id != report_id:
        raise HTTPException(404, "not_found")
    assets = {a.public_id: a.blob_id for a in db.scalars(select(ReportAsset).where(ReportAsset.report_version_id == v.id))}
    nonce = secrets.token_urlsafe(12)
    html = render_report(v.content, version=v.version, lang=lang, nonce=nonce, print_mode=False, pdf_url=None,
                         asset_url=lambda p: f"/api/blobs/{assets.get(p)}")
    return HTMLResponse(html, headers=_report_headers(nonce, img_self=True))


@router.post("/reports/{report_id}/versions/{version_id}/approve")
def approve(report_id: uuid.UUID, version_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    r = db.get(Report, report_id)
    v = db.get(ReportVersion, version_id)
    if r is None or v is None:
        raise HTTPException(404, "not_found")
    rs.approve_version(db, r, v, user.id)
    record_activity(db, "report", "version_approved", user_id=user.id, entity_type="report", entity_id=r.id,
                    details={"version": v.version})
    return report_view(db, r)


class PublishIn(BaseModel):
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    password: str | None = Field(default=None, min_length=6, max_length=128)
    allow_pdf: bool = True


def public_origin(db: Session, origin: RequestOrigin) -> str:
    configured = get_setting(db, "report.public_origin")
    return configured or origin.origin


@router.post("/reports/{report_id}/publish")
def publish(report_id: uuid.UUID, body: PublishIn, db: Session = Depends(get_db), user: User = Depends(current_user),
            origin: RequestOrigin = Depends(request_origin)) -> dict:
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "not_found")
    try:
        row, token = rs.publish(db, r, expires_at=rs.expires_in(body.expires_in_days), password=body.password,
                                allow_pdf=body.allow_pdf)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    record_activity(db, "report", "published", user_id=user.id, entity_type="report", entity_id=r.id,
                    details={"link": str(row.id)})
    # The raw token is shown exactly once; only its keyed hash is stored.
    return {"link_id": str(row.id), "url": f"{public_origin(db, origin)}/r/{token}", "path": f"/r/{token}"}


@router.post("/reports/{report_id}/links/{link_id}/revoke")
def revoke(report_id: uuid.UUID, link_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    t = db.get(ReportAccessToken, link_id)
    if t is None or t.report_id != report_id:
        raise HTTPException(404, "not_found")
    rs.revoke(db, t)
    record_activity(db, "report", "link_revoked", user_id=user.id, entity_type="report", entity_id=report_id)
    return {"ok": True}


@router.post("/reports/{report_id}/links/{link_id}/rotate")
def rotate(report_id: uuid.UUID, link_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user),
           origin: RequestOrigin = Depends(request_origin)) -> dict:
    t = db.get(ReportAccessToken, link_id)
    if t is None or t.report_id != report_id or t.revoked_at:
        raise HTTPException(404, "not_found")
    row, token = rs.rotate(db, t)
    record_activity(db, "report", "link_rotated", user_id=user.id, entity_type="report", entity_id=report_id)
    return {"link_id": str(row.id), "url": f"{public_origin(db, origin)}/r/{token}", "path": f"/r/{token}"}


@router.post("/reports/{report_id}/unpublish")
def unpublish(report_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "not_found")
    rs.revoke_all(db, r)
    record_activity(db, "report", "unpublished", user_id=user.id, entity_type="report", entity_id=r.id)
    return {"ok": True}


@router.get("/reports/{report_id}/versions/{version_id}/pdf")
def admin_pdf(report_id: uuid.UUID, version_id: uuid.UUID, lang: str = "en", db: Session = Depends(get_db),
              _: User = Depends(current_user)) -> Response:
    a = db.scalar(select(ReportAsset).where(ReportAsset.report_version_id == version_id, ReportAsset.kind == "pdf",
                                            ReportAsset.language == lang))
    if a is None:
        raise HTTPException(404, "pdf_not_ready")
    b = db.get(EvidenceBlob, a.blob_id)
    return Response(b.data, media_type="application/pdf",  # type: ignore[union-attr]
                    headers={"Content-Disposition": f'attachment; filename="report-v-{lang}.pdf"'})


@router.delete("/reports/{report_id}")
def delete_report(report_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "not_found")
    db.delete(r)
    record_activity(db, "report", "deleted", user_id=user.id, entity_type="report", entity_id=report_id)
    return {"ok": True}


# --- Public, unauthenticated report access ---------------------------------------------------------

def _report_headers(nonce: str, img_self: bool = True) -> dict[str, str]:
    return {
        "Content-Security-Policy": (
            f"default-src 'none'; style-src 'nonce-{nonce}'; font-src data:; img-src 'self' data:; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        ),
        "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }


def _unlock_cookie_name(link_id: uuid.UUID) -> str:
    return "lr_rp_" + hashlib.sha256(str(link_id).encode()).hexdigest()[:12]


def _unlock_value(link: ReportAccessToken) -> str:
    key = get_settings().session_secret.encode()
    return hmac.new(key, f"{link.id}:{link.password_hash}".encode(), hashlib.sha256).hexdigest()


def _limited(db: Session, request: Request) -> None:
    if not rate_limit(db, f"public:{client_ip(request)}", 120, 60):
        raise HTTPException(429, "too_many_requests")


def _resolve(db: Session, token: str, request: Request):  # type: ignore[no-untyped-def]
    _limited(db, request)
    res = rs.resolve_token(db, token)
    if res is None:
        return None
    link, report, version = res
    company = db.get(Company, report.company_id)
    if company is None or company.deleted_at is not None:
        return None  # public links of companies in the trash stop working
    if link.password_hash:
        cookie = request.cookies.get(_unlock_cookie_name(link.id))
        if not cookie or not hmac.compare_digest(cookie, _unlock_value(link)):
            return link, report, version, False
    return link, report, version, True


@public.get("/{token}", response_class=HTMLResponse)
def public_report(token: str, request: Request, lang: str | None = None, error: str | None = None,
                  db: Session = Depends(get_db)) -> HTMLResponse:
    nonce = secrets.token_urlsafe(12)
    res = _resolve(db, token, request)
    if res is None:
        db.commit()
        return HTMLResponse(render_message(lang or "en", "unavailable", nonce=nonce), status_code=404,
                            headers=_report_headers(nonce))
    link, report, version, unlocked = res
    language = lang if lang in ("en", "tr") else report.language
    if not unlocked:
        return HTMLResponse(render_message(language, "password_required", password_form_action=f"/r/{token}/unlock",
                                           error="wrong_password" if error else None, nonce=nonce),
                            status_code=401, headers=_report_headers(nonce))
    link.view_count += 1
    link.last_viewed_at = datetime.now(UTC)
    has_pdf = link.allow_pdf and db.scalar(select(ReportAsset.id).where(
        ReportAsset.report_version_id == version.id, ReportAsset.kind == "pdf", ReportAsset.language == language))
    html = render_report(version.content, version=version.version, lang=language, nonce=nonce, print_mode=False,
                         pdf_url=f"/r/{token}/pdf?lang={language}" if has_pdf else None,
                         asset_url=lambda p: f"/r/{token}/a/{p}")
    return HTMLResponse(html, headers=_report_headers(nonce))


@public.post("/{token}/unlock")
def unlock(token: str, request: Request, password: str = Form(..., max_length=128), lang: str = Form("en"),
           db: Session = Depends(get_db), origin: RequestOrigin = Depends(request_origin)) -> Response:
    if not rate_limit(db, f"public-unlock:{client_ip(request)}", 10, 300):
        raise HTTPException(429, "too_many_requests")
    res = rs.resolve_token(db, token)
    safe_lang = lang if lang in ("en", "tr") else "en"
    if res is None or not res[0].password_hash:
        return RedirectResponse(f"/r/{token}?lang={safe_lang}", status_code=303)
    link = res[0]
    if not verify_password(link.password_hash, password):
        return RedirectResponse(f"/r/{token}?lang={safe_lang}&error=1", status_code=303)
    resp = RedirectResponse(f"/r/{token}?lang={safe_lang}", status_code=303)
    resp.set_cookie(_unlock_cookie_name(link.id), _unlock_value(link), max_age=12 * 3600, httponly=True,
                    secure=origin.scheme == "https" or get_settings().is_production, samesite="lax", path="/r/")
    return resp


@public.get("/{token}/a/{public_id}")
def public_asset(token: str, public_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
    res = _resolve(db, token, request)
    if res is None or not res[3]:
        raise HTTPException(404, "not_found")
    version = res[2]
    a = db.scalar(select(ReportAsset).where(ReportAsset.public_id == public_id, ReportAsset.report_version_id == version.id,
                                            ReportAsset.kind == "screenshot"))
    if a is None:
        raise HTTPException(404, "not_found")
    b = db.get(EvidenceBlob, a.blob_id)
    if b is None:
        raise HTTPException(404, "not_found")
    return Response(b.data, media_type=b.content_type, headers={
        "Cache-Control": "private, max-age=600", "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
        "X-Content-Type-Options": "nosniff"})


@public.get("/{token}/pdf")
def public_pdf(token: str, request: Request, lang: str = Query("en"), db: Session = Depends(get_db)) -> Response:
    res = _resolve(db, token, request)
    if res is None or not res[3] or not res[0].allow_pdf:
        raise HTTPException(404, "not_found")
    version = res[2]
    a = db.scalar(select(ReportAsset).where(ReportAsset.report_version_id == version.id, ReportAsset.kind == "pdf",
                                            ReportAsset.language == (lang if lang in ("en", "tr") else "en")))
    if a is None:
        raise HTTPException(404, "not_found")
    b = db.get(EvidenceBlob, a.blob_id)
    return Response(b.data, media_type="application/pdf", headers={  # type: ignore[union-attr]
        "Content-Disposition": f'attachment; filename="report-v{version.version}-{lang}.pdf"',
        "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet", "Cache-Control": "private, no-store"})
