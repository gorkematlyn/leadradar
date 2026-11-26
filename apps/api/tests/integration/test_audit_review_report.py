"""End-to-end backend workflow against a controlled local fixture website:
audit → Action Required → administrator review → final score → report → publication → revocation."""

from __future__ import annotations

import os
import shutil
import threading
import uuid
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration

PORT = int(os.environ.get("LEADRADAR_TEST_FIXTURE_PORT", "18765"))
SITE = Path(__file__).parent.parent / "fixtures" / "site"


@pytest.fixture(scope="module")
def fixture_site():
    handler = partial(SimpleHTTPRequestHandler, directory=str(SITE))
    handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{PORT}/"
    srv.shutdown()


def chrome_available() -> bool:
    return bool(os.environ.get("CHROME_PATH") and os.path.exists(os.environ["CHROME_PATH"]))


def test_full_workflow(auth_client, fixture_site, db):
    from leadradar.core.app_settings import set_setting
    from leadradar.db.models import AuditFinding, Evidence, TrackingDetection, WebsiteAudit
    from leadradar.modules.website_audit.engine import execute_audit

    set_setting(db, "audit.lighthouse_enabled", False)
    set_setting(db, "audit.reuse_audit_days", 0)
    db.commit()
    cid = auth_client.post("/api/companies", json={"name": "Fixture Dental", "country": "NL", "industry": "dental_clinics",
                                                   "website": fixture_site}).json()["id"]
    r = auth_client.post(f"/api/companies/{cid}/audits", json={"mode": "full"})
    assert r.status_code == 200
    audit_id = uuid.UUID(r.json()["audit_id"])
    # Duplicate concurrent analysis of the same company is prevented.
    assert auth_client.post(f"/api/companies/{cid}/audits", json={"mode": "full"}).json()["audit_id"] == str(audit_id)
    if not chrome_available():
        os.environ["LEADRADAR_SKIP_BROWSER"] = "1"
    stages: list[str] = []
    out = execute_audit(audit_id, stages.append)
    assert out["status"] == "action_required" and out["reachable"]
    assert stages[0] == "http" and "persist" in stages
    db.expire_all()
    audit = db.get(WebsiteAudit, audit_id)
    findings = {f.rule_key: f for f in db.scalars(select(AuditFinding).where(AuditFinding.audit_id == audit_id))}
    assert findings["site.reachable"].result == "passed"
    assert findings["seo.meta_description"].result == "failed"
    assert findings["conv.booking"].result == "failed"  # relevant for dental clinics; fixture has none
    assert findings["site.https_available"].result == "failed"
    assert findings["conv.quote_form"].result == "not_applicable"
    assert audit.content_fingerprint and audit.pages_audited
    tracking = {t.technology: t.status for t in db.scalars(select(TrackingDetection).where(TrackingDetection.audit_id == audit_id))}
    assert tracking["ga4"] == "detected" and tracking["meta_pixel"] == "not_detected"
    if chrome_available():
        assert findings["visual.horizontal_overflow"].result == "failed"
        shots = db.scalars(select(Evidence).where(Evidence.audit_id == audit_id, Evidence.kind == "screenshot")).all()
        assert len(shots) >= 1
    detail = auth_client.get(f"/api/companies/{cid}").json()
    assert detail["analysis_status"] == "action_required" and detail["preliminary_score"] is not None
    queue_items = auth_client.get("/api/review-queue").json()
    assert any(i["audit_id"] == str(audit_id) for i in queue_items)

    # --- administrator review ---
    a = auth_client.get(f"/api/audits/{audit_id}").json()
    keys = [q["key"] for q in a["questions"]]
    assert "visual_findings_valid" in keys
    answers = [{"question_key": "visual_findings_valid", "answer": "yes"},
               {"question_key": "visual_redesign", "answer": "yes", "note": "dated layout"},
               {"question_key": "brand_identity", "answer": "unknown"}]
    approve = [s["id"] for s in a["screenshots"]]
    r = auth_client.post(f"/api/audits/{audit_id}/review", json={"answers": answers, "approve_evidence": approve})
    assert r.status_code == 200, r.text
    final = r.json()["score"]
    assert final["stage"] == "final"
    applied = {x["key"] for c in final["breakdown"]["categories"].values() for x in c["rules"]}
    assert "need.visual_redesign" in applied
    assert auth_client.post(f"/api/audits/{audit_id}/review", json={"answers": [{"question_key": "nope", "answer": "yes"}]}).status_code == 400
    detail = auth_client.get(f"/api/companies/{cid}").json()
    assert detail["analysis_status"] == "completed" and detail["final_score"] == final["score"]
    assert detail["crm_status"] == "new"  # audits never overwrite CRM status

    # --- override preserves original ---
    auth_client.post(f"/api/companies/{cid}/score-override", json={"score": 91, "reason": "Known budget"})
    detail = auth_client.get(f"/api/companies/{cid}").json()
    assert detail["lead_score"] == 91 and detail["override"]["original"] == final["score"]

    # --- reports ---
    auth_client.patch(f"/api/companies/{cid}", json={"notes": "INTERNAL-SECRET-NOTE", "email": "owner@fixture-dental.nl"})
    rep = auth_client.post("/api/reports", json={"company_id": cid, "title": "Digital audit", "mode": "snapshot"}).json()
    rid = rep["id"]
    v1 = rep["versions"][0]["id"]
    assert auth_client.post(f"/api/reports/{rid}/publish", json={}).status_code == 400  # requires approval first
    auth_client.post(f"/api/reports/{rid}/versions/{v1}/approve")
    snap = auth_client.post(f"/api/reports/{rid}/publish", json={}).json()
    page = auth_client.get(f"/r/{snap['path'].split('/')[-1]}")
    assert page.status_code == 200 and "Fixture Dental" in page.text
    for secret in ("INTERNAL-SECRET-NOTE", "owner@fixture-dental.nl", "lead_score", "confidence", "crm_status", "G-ABC1234567"):
        assert secret not in page.text
    assert "noindex" in page.headers["x-robots-tag"]
    assert "default-src 'none'" in page.headers["content-security-policy"]

    # live link follows newly approved versions; snapshot link stays pinned
    auth_client.patch(f"/api/reports/{rid}", json={"mode": "live", "title": "Digital audit v2"})
    live = auth_client.post(f"/api/reports/{rid}/publish", json={"password": "open-sesame-1"}).json()
    v2 = auth_client.post(f"/api/reports/{rid}/versions").json()["id"]
    live_token = live["path"].split("/")[-1]
    assert auth_client.get(f"/r/{live_token}").status_code == 401  # password protected
    unlock = auth_client.c.post(f"/r/{live_token}/unlock", data={"password": "open-sesame-1", "lang": "tr"},
                                follow_redirects=False)
    assert unlock.status_code == 303
    assert "Digital audit v2" not in auth_client.get(f"/r/{live_token}").text  # v2 not approved yet
    auth_client.post(f"/api/reports/{rid}/versions/{v2}/approve")
    assert "Digital audit v2" in auth_client.get(f"/r/{live_token}?lang=tr").text
    snap_page = auth_client.get(f"/r/{snap['path'].split('/')[-1]}").text
    assert "Digital audit v2" not in snap_page

    # revocation and invalid tokens
    links = auth_client.get(f"/api/reports/{rid}").json()["links"]
    for link in links:
        auth_client.post(f"/api/reports/{rid}/links/{link['id']}/revoke")
    assert auth_client.get(f"/r/{snap['path'].split('/')[-1]}").status_code == 404
    assert auth_client.get("/r/not-a-real-token").status_code == 404

    # --- PDF generation (requires Chromium) ---
    if chrome_available():
        from leadradar.modules.reporting.service import handle_pdf

        res = handle_pdf(SimpleNamespace(payload={"version_id": v2, "lang": "tr"}))
        assert res.result["bytes"] > 1000
        pdf = auth_client.get(f"/api/reports/{rid}/versions/{v2}/pdf?lang=tr")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_verified_absent_website_scoring(auth_client):
    cid = auth_client.post("/api/companies", json={"name": "No Site Bakery", "country": "TR", "industry": "restaurants"}).json()["id"]
    assert auth_client.get(f"/api/companies/{cid}").json()["website_status"] == "not_found"
    r = auth_client.post(f"/api/companies/{cid}/verify-website", json={"absent": True})
    assert r.json()["website_status"] == "verified_absent"
    d = auth_client.get(f"/api/companies/{cid}").json()
    need = d["score"]["breakdown"]["categories"]["service_need"]
    assert [x["key"] for x in need["rules"]] == ["need.no_website"]
    assert any(s["service"] == "website_design" for s in d["service_scores_detail"])


def test_ssrf_quick_audit_rejected(auth_client):
    for url in ("http://169.254.169.254/latest/", "http://localhost:5432", "http://10.0.0.5/"):
        assert auth_client.post("/api/companies/quick-audit", json={"url": url}).status_code == 400


def test_egress_proxy_blocks_private_destinations():
    import httpx

    from leadradar.modules.netsafe.proxy import get_egress_proxy

    proxy = get_egress_proxy()
    with httpx.Client(proxy=proxy.url, timeout=5, trust_env=False) as c:
        r = c.get("http://10.0.0.1/")
        assert r.status_code == 403
    if shutil.which("true"):
        assert any("10.0.0.1" in b or "blocked" in b for b in proxy.blocked)
