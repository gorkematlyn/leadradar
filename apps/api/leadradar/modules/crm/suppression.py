"""System-wide Do Not Contact suppression."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from leadradar.db.models import Company, CompanySource, SuppressionEntry
from leadradar.modules.crm.normalize import normalize_domain, normalize_phone

KINDS = {"company", "domain", "email", "phone", "source"}


def normalize_value(kind: str, value: str) -> str:
    value = value.strip()
    if kind == "domain":
        return normalize_domain(value) or value.lower()
    if kind == "email":
        return value.lower()
    if kind == "phone":
        return normalize_phone(value) or value
    return value


def active_entries(db: Session) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {k: set() for k in KINDS}
    for kind, value in db.execute(select(SuppressionEntry.kind, SuppressionEntry.value).where(
            SuppressionEntry.removed_at.is_(None))):
        out[kind].add(value)
    return out


def is_suppressed(
    entries: dict[str, set[str]], *, company_id: str | None = None, domain: str | None = None,
    email: str | None = None, phone: str | None = None, source_keys: list[str] | None = None,
) -> bool:
    get = lambda k: entries.get(k, set())  # noqa: E731
    if company_id and company_id in get("company"):
        return True
    if domain and domain in get("domain"):
        return True
    if email and email.lower() in get("email"):
        return True
    if phone and phone in get("phone"):
        return True
    return any(k in get("source") for k in (source_keys or []))


def suppress_company(db: Session, company: Company, reason: str | None, user_id: uuid.UUID | None) -> list[SuppressionEntry]:
    """Mark DNC and create identity entries so re-imports stay suppressed."""
    created = []
    values = [("company", str(company.id))]
    if company.canonical_domain:
        values.append(("domain", company.canonical_domain))
    if company.email:
        values.append(("email", company.email.lower()))
    if company.phone_normalized:
        values.append(("phone", company.phone_normalized))
    for src in db.scalars(select(CompanySource).where(CompanySource.company_id == company.id)):
        values.append(("source", f"{src.source}:{src.source_key}"))
    for kind, value in values:
        exists = db.scalar(select(SuppressionEntry).where(
            SuppressionEntry.kind == kind, SuppressionEntry.value == value, SuppressionEntry.removed_at.is_(None)))
        if exists is None:
            e = SuppressionEntry(kind=kind, value=value, reason=reason, company_id=company.id, created_by=user_id)
            db.add(e)
            created.append(e)
    company.do_not_contact = True
    company.crm_status = "do_not_contact"
    db.flush()
    return created


def add_entry(db: Session, kind: str, value: str, reason: str | None, user_id: uuid.UUID | None) -> SuppressionEntry:
    if kind not in KINDS:
        raise ValueError("invalid suppression kind")
    value = normalize_value(kind, value)
    e = db.scalar(select(SuppressionEntry).where(
        SuppressionEntry.kind == kind, SuppressionEntry.value == value, SuppressionEntry.removed_at.is_(None)))
    if e:
        return e
    e = SuppressionEntry(kind=kind, value=value, reason=reason, created_by=user_id)
    db.add(e)
    db.flush()
    apply_entry(db, e)
    return e


def apply_entry(db: Session, e: SuppressionEntry) -> int:
    """Flag existing matching companies."""
    cond = None
    if e.kind == "company":
        try:
            cond = Company.id == uuid.UUID(e.value)
        except ValueError:
            return 0
    elif e.kind == "domain":
        cond = Company.canonical_domain == e.value
    elif e.kind == "email":
        cond = Company.email.ilike(e.value)
    elif e.kind == "phone":
        cond = Company.phone_normalized == e.value
    elif e.kind == "source":
        source, _, key = e.value.partition(":")
        sub = select(CompanySource.company_id).where(CompanySource.source == source, CompanySource.source_key == key)
        cond = Company.id.in_(sub)
    if cond is None:
        return 0
    res = db.execute(update(Company).where(cond).values(do_not_contact=True, crm_status="do_not_contact"))
    return res.rowcount or 0


def remove_entry(db: Session, e: SuppressionEntry, reason: str, user_id: uuid.UUID | None) -> None:
    """Soft-remove (kept for audit history). Companies are not automatically un-suppressed
    if another active entry still matches them."""
    e.removed_at = datetime.now(UTC)
    e.removed_by = user_id
    e.removal_reason = reason
    db.flush()
    if e.company_id:
        company = db.get(Company, e.company_id)
        if company is not None:
            entries = active_entries(db)
            if not is_suppressed(entries, company_id=str(company.id), domain=company.canonical_domain,
                                 email=company.email, phone=company.phone_normalized):
                company.do_not_contact = False
                if company.crm_status == "do_not_contact":
                    company.crm_status = "new"


def suppressed_condition():  # type: ignore[no-untyped-def]
    """SQL condition matching suppressed companies (for exports)."""
    return or_(Company.do_not_contact.is_(True))
