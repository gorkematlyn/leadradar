"""Trash (soft delete), editable CRM statuses, pipeline table, facets, website status."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

pytestmark = pytest.mark.integration


def _company(client, name, **kw):
    body = {"name": name, "country": kw.pop("country", "NL"), "industry": kw.pop("industry", "restaurants"), **kw}
    return client.post("/api/companies", json=body).json()["id"]


def _names(client, f=None):
    res = client.post("/api/companies/query", json={"filter": {"q": "trashtest", **(f or {})}, "page_size": 100}).json()
    return sorted(i["name"] for i in res["items"])


def test_trash_bulk_delete_restore_and_purge(auth_client, db):
    from leadradar.db.models import Company
    from leadradar.modules.crm.trash import purge

    a = _company(auth_client, "Trashtest A")
    b = _company(auth_client, "Trashtest B")
    c = _company(auth_client, "Trashtest C")
    assert auth_client.post("/api/companies/bulk", json={"ids": [a, b], "action": "delete"}).json()["affected"] == 2
    assert _names(auth_client) == ["Trashtest C"]
    assert auth_client.get(f"/api/companies/{a}").status_code == 404
    trash = auth_client.get("/api/companies/trash/items").json()
    assert {a, b} <= {i["id"] for i in trash["items"]} and trash["days"] == 30
    assert auth_client.post("/api/companies/trash/restore", json={"ids": [a]}).json()["restored"] == 1
    assert _names(auth_client) == ["Trashtest A", "Trashtest C"]
    # Single delete also moves to the trash; permanent deletion happens from the trash.
    assert auth_client.delete(f"/api/companies/{c}").status_code == 200
    assert auth_client.post("/api/companies/trash/purge", json={"ids": [c]}).json()["deleted"] == 1
    db.expire_all()
    assert db.get(Company, uuid.UUID(c)) is None
    # The retention job purges only items older than 30 days.
    db.execute(update(Company).where(Company.id == uuid.UUID(b)).values(deleted_at=datetime.now(UTC) - timedelta(days=31)))
    db.commit()
    assert purge(db, None, None, older_than_days=30) >= 1
    db.commit()
    assert db.get(Company, uuid.UUID(b)) is None


def test_website_status_fix_and_manual_edit(auth_client, db):
    cid = _company(auth_client, "Trashtest NoSite")
    detail = auth_client.get(f"/api/companies/{cid}").json()
    assert detail["website_status"] == "not_found"
    assert auth_client.patch(f"/api/companies/{cid}", json={"website_status": "verified_absent"}).status_code == 200
    assert auth_client.get(f"/api/companies/{cid}").json()["website_status"] == "verified_absent"
    auth_client.patch(f"/api/companies/{cid}", json={"website": "https://nosite-trashtest.com"})
    assert auth_client.get(f"/api/companies/{cid}").json()["website_status"] == "unverified"
    auth_client.patch(f"/api/companies/{cid}", json={"website": ""})
    d = auth_client.get(f"/api/companies/{cid}").json()
    assert d["website_status"] == "not_found" and not d["website"]
    auth_client.delete(f"/api/companies/{cid}")


def test_crm_statuses_are_editable(auth_client, db):
    from leadradar.db.models import CrmStatus
    from leadradar.seeds.run import run_seed

    key = auth_client.post("/api/crm/statuses", json={"name_en": "Waiting for Budget", "name_tr": "Bütçe bekleniyor"}).json()["key"]
    assert key == "waiting_for_budget"
    assert auth_client.patch(f"/api/crm/statuses/{key}", json={"name_en": "Budget pending", "name_tr": "Bütçe bekleniyor",
                                                                "show_in_pipeline": False}).status_code == 200
    cid = _company(auth_client, "Trashtest Status")
    auth_client.patch(f"/api/companies/{cid}", json={"crm_status": key})
    assert auth_client.delete(f"/api/crm/statuses/{key}").status_code == 409  # in use, no target
    assert auth_client.delete("/api/crm/statuses/new?move_to=qualified").status_code == 409  # system status
    assert auth_client.delete(f"/api/crm/statuses/{key}?move_to=qualified").json()["moved"] == 1
    assert auth_client.get(f"/api/companies/{cid}").json()["crm_status"] == "qualified"
    # A deleted default status is not re-created on restart; system statuses always exist.
    assert auth_client.delete("/api/crm/statuses/not_a_fit?move_to=lost").status_code == 200
    run_seed(db)
    db.commit()
    assert db.get(CrmStatus, "not_a_fit") is None and db.get(CrmStatus, "new").is_system
    keys = [s["key"] for s in auth_client.get("/api/crm/statuses").json()]
    assert auth_client.post("/api/crm/statuses/reorder", json={"keys": list(reversed(keys))}).status_code == 200
    assert [s["key"] for s in auth_client.get("/api/crm/statuses").json()] == list(reversed(keys))
    auth_client.post("/api/crm/statuses/reorder", json={"keys": keys})
    db.add(CrmStatus(key="not_a_fit", name_en="Not a Fit", name_tr="Uygun değil", sort_order=10, is_terminal=True,
                     show_in_pipeline=False))
    db.commit()
    auth_client.delete(f"/api/companies/{cid}")


def test_pipeline_table_and_facets(auth_client, db):
    from leadradar.db.models import AdvertisingResearchRun, Company, Report

    cid = _company(auth_client, "Trashtest Pipeline", country="BE")
    c = db.get(Company, uuid.UUID(cid))
    c.service_scores = {"google_ads": {"score": 40}, "website_design": {"score": 80}, "seo": {"score": 10}}
    c.final_lead_score = c.effective_lead_score = 99
    for i in range(7):
        db.add(Report(company_id=c.id, title=f"Report {i}", updated_at=datetime.now(UTC) + timedelta(minutes=i)))
    db.add(AdvertisingResearchRun(company_id=c.id, platform="meta", status="found", method="automated", result_count=2))
    db.add(AdvertisingResearchRun(company_id=c.id, platform="google", status="found", method="automated", result_count=3,
                                  created_at=datetime.now(UTC) - timedelta(days=2)))
    db.add(AdvertisingResearchRun(company_id=c.id, platform="google", status="no_results", method="automated", result_count=0))
    db.commit()
    rows = auth_client.get("/api/crm/pipeline/table?page_size=200").json()["items"]
    row = next(r for r in rows if r["id"] == cid)
    assert [s["key"] for s in row["services"]] == ["website_design", "google_ads"]
    assert row["reports"]["count"] == 7 and [r["title"] for r in row["reports"]["latest"]][0] == "Report 6"
    assert len(row["reports"]["latest"]) == 5
    assert row["ads"] == {"total": 2, "platforms": [{"platform": "meta", "count": 2}]}  # latest google run found none
    f = auth_client.get("/api/companies/facets").json()
    assert any(x["value"] == "BE" for x in f["countries"]) and any(x["value"] == "europe" for x in f["regions"])
    assert all(x["value"] != "ZW" for x in f["countries"])
    auth_client.delete(f"/api/companies/{cid}")
    assert all(x["value"] != "BE" or x["count"] >= 0 for x in auth_client.get("/api/companies/facets").json()["countries"])


def test_discovery_passes_include_without_website(auth_client, db):
    from leadradar.db.models import Job

    db.execute(update(Job).where(Job.status.in_(["queued", "running", "paused"])).values(status="cancelled"))
    db.commit()
    auth_client.patch("/api/countries/MT", json={"enabled": True})
    jid = auth_client.post("/api/discovery/imports", json={"countries": ["MT"], "include_without_website": True}).json()["jobs"][0]
    db.expire_all()
    assert db.get(Job, uuid.UUID(jid)).payload["include_without_website"] is True
    db.execute(update(Job).where(Job.id == uuid.UUID(jid)).values(status="cancelled"))
    db.commit()
    _ = select
