from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

pytestmark = pytest.mark.integration


def _clear_jobs(db):
    from leadradar.db.models import Job

    db.execute(update(Job).where(Job.status.in_(["queued", "running", "paused"])).values(status="cancelled"))
    db.commit()


def test_seed_is_idempotent(db):
    from leadradar.db.models import Country, Industry, ScoringRule
    from leadradar.seeds.run import run_seed

    before = (db.scalar(select(func.count()).select_from(Country)), db.scalar(select(func.count()).select_from(ScoringRule)))
    ind = db.scalar(select(Industry).where(Industry.key == "restaurants"))
    ind.name_en, ind.admin_customized = "Eateries", True
    db.commit()
    run_seed(db)
    db.commit()
    after = (db.scalar(select(func.count()).select_from(Country)), db.scalar(select(func.count()).select_from(ScoringRule)))
    assert before == after
    assert db.scalar(select(Industry.name_en).where(Industry.key == "restaurants")) == "Eateries"
    assert db.scalar(select(func.count()).select_from(Industry)) == 12


def test_initial_import_scheduled_once(db):
    from leadradar.core.app_settings import set_setting
    from leadradar.db.models import Job
    from leadradar.jobs.scheduler import schedule_initial_import

    _clear_jobs(db)
    set_setting(db, "discovery.initial_import_scheduled", False, admin=False)
    first = schedule_initial_import(db)
    second = schedule_initial_import(db)
    db.commit()
    assert first == ["TR", "NL", "DE", "GB", "US"] and second == []
    n = db.scalar(select(func.count()).select_from(Job).where(Job.type == "geofabrik_country_import", Job.status == "queued"))
    assert n == 5
    _clear_jobs(db)


def test_job_claim_limits_idempotency_and_recovery(db):
    from leadradar.db.models import Job
    from leadradar.jobs import queue

    _clear_jobs(db)
    a = queue.enqueue(db, "website_audit", "a", {}, idempotency_key="t:a")
    assert queue.enqueue(db, "website_audit", "a2", {}, idempotency_key="t:a").id == a.id
    b = queue.enqueue(db, "website_audit", "b", {})
    c = queue.enqueue(db, "quick_audit", "c", {}, concurrency_key="property:x")
    d = queue.enqueue(db, "quick_audit", "d", {}, concurrency_key="property:x")
    db.commit()
    j1 = queue.claim(db, "analysis", "w1")
    db.commit()
    assert j1.id in (c.id, d.id) or j1.id == a.id
    claimed = [j1.id]
    for _ in range(4):
        j = queue.claim(db, "analysis", "w2")
        db.commit()
        if j:
            claimed.append(j.id)
    heavy = [x for x in claimed if x in (a.id, b.id)]
    same_key = [x for x in claimed if x in (c.id, d.id)]
    assert len(heavy) == 1, "heavy concurrency limit (1) must hold"
    assert len(same_key) == 1, "jobs sharing a concurrency key must not run concurrently"
    # Simulate a crashed worker: expire the lease and recover.
    db.execute(update(Job).where(Job.id.in_(claimed)).values(lease_until=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    assert queue.recover_stale(db) == len(claimed)
    db.commit()
    for jid in claimed:
        j = db.get(Job, jid)
        db.refresh(j)
        assert j.status == "queued" and j.run_at > datetime.now(UTC)
    _clear_jobs(db)


def test_retry_limit_dead_letters(db):
    from leadradar.jobs import queue

    _clear_jobs(db)
    j = queue.enqueue(db, "ad_research", "x", {})
    j.max_attempts = 1
    db.commit()
    claimed = queue.claim(db, "analysis", "w")
    queue.fail(db, claimed, "boom")
    db.commit()
    assert claimed.status == "dead"


def test_upsert_dedupe_branch_and_suppression(db):
    from leadradar.db.models import Company, DuplicateCandidate
    from leadradar.modules.crm.companies import RecordInput, upsert_record
    from leadradar.modules.crm.suppression import active_entries, suppress_company

    base = dict(country_iso2="NL", industry_keys=["dental_clinics"], website="https://www.smile-dental-test.nl/")
    a = upsert_record(db, RecordInput(source="osm", source_key="node/9001", name="Smile Dental", latitude=52.37,
                                      longitude=4.89, **base), {}).company
    same = upsert_record(db, RecordInput(source="csv", source_key="csv:1", name="Smile Dental Amsterdam",
                                         latitude=52.3701, longitude=4.8901, **base), {})
    assert same.company.id == a.id and same.action == "matched"
    branch = upsert_record(db, RecordInput(source="osm", source_key="node/9002", name="Smile Dental Utrecht",
                                           latitude=52.09, longitude=5.12, **base), {})
    assert branch.company.id != a.id and branch.duplicate_candidates == 1
    assert branch.company.website_property_id == a.website_property_id  # shared web property, audit reuse
    ids = sorted([a.id, branch.company.id], key=str)
    dup = db.scalar(select(DuplicateCandidate).where(DuplicateCandidate.company_a_id == ids[0],
                                                     DuplicateCandidate.company_b_id == ids[1]))
    assert "same_domain" in dup.reasons
    suppress_company(db, a, "requested", None)
    db.commit()
    again = upsert_record(db, RecordInput(source="osm", source_key="node/9003", name="Smile Dental Haarlem",
                                          latitude=52.38, longitude=4.63, **base), active_entries(db))
    assert again.company.do_not_contact  # same canonical domain is suppressed system-wide
    db.delete(db.get(Company, a.id))
    db.commit()
    reimport = upsert_record(db, RecordInput(source="osm", source_key="node/9001", name="Smile Dental", latitude=52.37,
                                             longitude=4.89, **base), active_entries(db))
    assert reimport.company.do_not_contact, "suppression survives deletion and re-import"
    db.commit()


def test_admin_confirmed_values_not_overwritten(db):
    from leadradar.modules.crm.companies import RecordInput, _set_field, upsert_record

    c = upsert_record(db, RecordInput(source="osm", source_key="node/777", name="Old Name", country_iso2="TR",
                                      phone="0212 000 00 00"), {}).company
    _set_field(db, c, "name", "Confirmed Name", "manual", force=True)
    upsert_record(db, RecordInput(source="osm", source_key="node/777", name="Imported Name", country_iso2="TR"), {})
    assert c.name == "Confirmed Name"
    db.commit()


def test_merge_preserves_crm_records(db):
    from leadradar.db.models import Company, CrmActivity, MergeHistory
    from leadradar.modules.crm.companies import RecordInput, merge_companies, upsert_record

    t = upsert_record(db, RecordInput(source="manual", source_key="m:1", name="Target Co", country_iso2="DE"), {}).company
    s = upsert_record(db, RecordInput(source="manual", source_key="m:2", name="Source Co", country_iso2="DE",
                                      phone="+49 30 1234567"), {}).company
    db.add(CrmActivity(company_id=s.id, kind="note", title="keep me", occurred_at=datetime.now(UTC)))
    db.flush()
    merge_companies(db, t, s, None)
    db.commit()
    assert db.get(Company, s.id).merged_into_id == t.id
    assert db.scalar(select(func.count()).select_from(CrmActivity).where(CrmActivity.company_id == t.id,
                                                                          CrmActivity.title == "keep me")) == 1
    assert t.phone_normalized == "+49301234567"
    assert db.scalar(select(MergeHistory).where(MergeHistory.merged_company_id == s.id)) is not None


def test_company_filters_tags_and_export(auth_client, db):
    r = auth_client.post("/api/companies", json={"name": "Filter Alpha", "country": "TR", "industry": "restaurants",
                                                 "website": "https://alpha-filter-test.com.tr"})
    alpha = r.json()["id"]
    beta = auth_client.post("/api/companies", json={"name": "Filter Beta", "country": "TR", "industry": "restaurants"}).json()["id"]
    t1 = auth_client.post("/api/tags", json={"name": "FT-One"}).json()["id"]
    t2 = auth_client.post("/api/tags", json={"name": "FT-Two"}).json()["id"]
    auth_client.put(f"/api/companies/{alpha}/tags", json={"tag_ids": [t1, t2]})
    auth_client.put(f"/api/companies/{beta}/tags", json={"tag_ids": [t1]})

    def names(f):
        res = auth_client.post("/api/companies/query", json={"filter": {"q": "filter ", **f}, "page_size": 50}).json()
        return sorted(i["name"] for i in res["items"])

    assert names({"tags_any": ["FT-One"]}) == ["Filter Alpha", "Filter Beta"]
    assert names({"tags_all": ["FT-One", "FT-Two"]}) == ["Filter Alpha"]
    assert names({"tags_any": ["FT-One"], "tags_exclude": ["FT-Two"]}) == ["Filter Beta"]
    assert names({"has_website": True}) == ["Filter Alpha"]
    assert auth_client.post(f"/api/companies/{beta}/do-not-contact", json={"reason": "asked"}).status_code == 200
    assert names({}) == ["Filter Alpha"]  # DNC excluded from normal lists
    assert names({"dnc": "only"}) == ["Filter Beta"]
    csv_text = auth_client.post("/api/companies/export", json={"filter": {"q": "filter", "dnc": "include"}}).text
    assert "Filter Alpha" in csv_text and "Filter Beta" not in csv_text
    r = auth_client.patch(f"/api/companies/{beta}", json={"crm_status": "contacted"})
    assert r.status_code == 409
