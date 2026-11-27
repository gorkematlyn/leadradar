"""Discovery import controls, job/notification housekeeping, scoring no-op saves and
provider URL editing."""

from __future__ import annotations

import hashlib
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import select, update

pytestmark = pytest.mark.integration


def _clear_jobs(db):
    from leadradar.db.models import Job

    db.execute(update(Job).where(Job.status.in_(["queued", "running", "paused"])).values(status="cancelled"))
    db.commit()


def test_failed_dependency_does_not_block_later_regions(db):
    from leadradar.jobs import queue

    _clear_jobs(db)
    a = queue.enqueue(db, "geofabrik_extract_import", "region a", {}, concurrency_key="t-geo")
    b = queue.enqueue(db, "geofabrik_extract_import", "region b", {}, depends_on=[a.id], concurrency_key="t-geo")
    db.commit()
    first = queue.claim(db, "discovery", "w")
    assert first.id == a.id
    assert queue.claim(db, "discovery", "w") is None  # b waits while a is running
    queue.fail(db, first, "boom", retryable=False)
    db.commit()
    nxt = queue.claim(db, "discovery", "w")
    assert nxt is not None and nxt.id == b.id
    queue.complete(db, nxt)
    db.commit()


def _make_batch(db, iso2: str, statuses: list[str]):
    from leadradar.db.models import ImportRun
    from leadradar.jobs import queue

    parent = queue.enqueue(db, "geofabrik_country_import", f"Import {iso2}", {"country": iso2})
    parent.status = "completed"
    children = []
    for i, st in enumerate(statuses):
        run = ImportRun(source="geofabrik", country_iso2=iso2, extract_id=f"t/{iso2}-{i}", status="queued", file_size=100)
        db.add(run)
        db.flush()
        j = queue.enqueue(db, "geofabrik_extract_import", f"Import region {i} ({iso2})",
                          {"country": iso2, "extract_id": run.extract_id, "size": 100, "import_run_id": str(run.id),
                           "region_name": f"Region {i}"}, parent_id=parent.id)
        j.status = st
        run.job_id = j.id
        if st == "completed":
            run.status = "completed"
        children.append((j, run))
    db.commit()
    return parent, children


def test_country_progress_cancel_and_clear(auth_client, db):
    from leadradar.db.models import ImportRun, Notification
    from leadradar.modules.crm.notifications import notify

    _clear_jobs(db)
    assert auth_client.patch("/api/countries/IS", json={"enabled": True}).status_code == 200
    parent, children = _make_batch(db, "IS", ["completed", "queued", "queued"])
    countries = {c["iso2"]: c for c in auth_client.get("/api/countries").json()}
    p = countries["IS"]["progress"]
    assert countries["IS"]["import_status"] == "queued"
    assert (p["regions_done"], p["regions_total"], p["bytes_done"], p["bytes_total"]) == (1, 3, 100, 300)
    assert any(x["iso2"] == "IS" for x in auth_client.get("/api/discovery/progress").json())

    # Pause / resume / cancel the whole country at once.
    assert auth_client.post("/api/discovery/countries/IS/action", json={"action": "pause"}).json()["affected"] == 2
    assert {c["iso2"]: c for c in auth_client.get("/api/countries").json()}["IS"]["import_status"] == "paused"
    auth_client.post("/api/discovery/countries/IS/action", json={"action": "resume"})
    assert auth_client.post("/api/discovery/countries/IS/action", json={"action": "cancel"}).json()["affected"] == 2
    db.expire_all()
    runs = db.scalars(select(ImportRun).where(ImportRun.country_iso2 == "IS")).all()
    assert sorted(r.status for r in runs) == ["cancelled", "cancelled", "completed"]
    assert {c["iso2"]: c for c in auth_client.get("/api/countries").json()}["IS"]["import_status"] == "partial"

    # A failure notification disappears when its job record is deleted.
    failed_job = children[1][0]
    notify(db, "import_failed", "notifications.importFailedRegion", {"country": "IS", "region": "x"},
           dedupe_key=f"import_failed:{failed_job.id}", severity="error")
    db.commit()
    assert auth_client.post("/api/jobs/delete", json={"ids": [str(failed_job.id)]}).json()["deleted"] == 1
    assert db.scalar(select(Notification.id).where(Notification.dedupe_key == f"import_failed:{failed_job.id}")) is None
    # Queued/running jobs are never deleted by the clean-up.
    _, active = _make_batch(db, "IS", ["queued"])
    auth_client.post("/api/jobs/delete", json={})
    db.expire_all()
    assert db.get(type(active[0][0]), active[0][0].id) is not None
    deleted = auth_client.delete("/api/discovery/imports").json()["deleted"]
    assert deleted >= 2
    db.expire_all()
    remaining = db.scalars(select(ImportRun).where(ImportRun.country_iso2 == "IS")).all()
    assert [r.id for r in remaining] == [active[0][1].id]
    _clear_jobs(db)


def test_geo_selection_names_are_unique_with_overwrite(auth_client):
    body = {"name": "Benelux test", "regions": [], "countries": ["NL", "BE"], "industries": []}
    first = auth_client.post("/api/geo-selections", json=body)
    assert first.status_code == 200
    assert auth_client.post("/api/geo-selections", json={**body, "name": "benelux TEST"}).status_code == 409
    over = auth_client.post("/api/geo-selections?overwrite=true", json={**body, "countries": ["NL"]}).json()
    assert over["overwritten"] and over["id"] == first.json()["id"]
    other = auth_client.post("/api/geo-selections", json={**body, "name": "Other test"}).json()["id"]
    assert auth_client.put(f"/api/geo-selections/{other}", json={**body, "name": "Benelux test"}).status_code == 409
    assert auth_client.put(f"/api/geo-selections/{other}", json={**body, "name": "Renamed test"}).status_code == 200
    sels = {s["name"]: s for s in auth_client.get("/api/geo-selections").json()}
    assert sels["Benelux test"]["countries"] == ["NL"] and "Renamed test" in sels
    assert auth_client.delete(f"/api/geo-selections/{other}").status_code == 200


def test_scoring_save_without_changes_keeps_version(auth_client):
    prof = auth_client.get("/api/scoring/profiles").json()[0]
    v = prof["version"]
    r = auth_client.patch(f"/api/scoring/profiles/{prof['id']}", json={"thresholds": prof["thresholds"]}).json()
    assert r["changed"] is False and r["version"] == v
    changed = {**prof["thresholds"], "high_priority": prof["thresholds"]["high_priority"] - 1}
    r = auth_client.patch(f"/api/scoring/profiles/{prof['id']}", json={"thresholds": changed}).json()
    assert r["changed"] is True and r["version"] == v + 1
    auth_client.patch(f"/api/scoring/profiles/{prof['id']}", json={"thresholds": prof["thresholds"]})
    rule = prof["rules"][0]
    assert auth_client.patch(f"/api/scoring/rules/{rule['id']}", json={"enabled": rule["enabled"]}).json()["changed"] is False


def test_notifications_clear_and_dashboard_warnings(auth_client, db):
    from leadradar.modules.crm.notifications import notify

    notify(db, "x", "notifications.lowDisk", {"free_gb": 1, "reserve_gb": 5}, severity="warning")
    db.commit()
    assert auth_client.get("/api/dashboard").json()["warnings"]
    assert auth_client.post("/api/dashboard/warnings/clear", json={}).status_code == 200
    dash = auth_client.get("/api/dashboard").json()
    assert dash["warnings"] == [] and dash["metrics"]["failed_jobs_24h"] == 0
    assert auth_client.post("/api/notifications/delete", json={}).status_code == 200
    assert auth_client.get("/api/notifications").json()["items"] == []


def test_provider_urls_editable_and_kept_by_seed(auth_client, db):
    from leadradar.seeds.run import run_seed

    url = "https://www.facebook.com/ads/library/?edited=1"
    assert auth_client.patch("/api/ad-providers/meta", json={"official_source_url": "javascript:alert(1)"}).status_code == 400
    assert auth_client.patch("/api/ad-providers/meta", json={"manual_search_url_template": "https://x.test/?q={bad}"}).status_code == 400
    assert auth_client.patch("/api/ad-providers/meta", json={"official_source_url": url,
                                                            "manual_search_url_template": "https://x.test/?q={query}"}).status_code == 200
    run_seed(db)
    db.commit()
    meta = {p["key"]: p for p in auth_client.get("/api/ad-providers").json()}["meta"]
    assert meta["official_source_url"] == url and meta["manual_search_url_template"] == "https://x.test/?q={query}"


class _Redirecting(BaseHTTPRequestHandler):
    payload = b"PBF-DATA" * 1000

    def log_message(self, *a):  # noqa: D401
        pass

    def do_GET(self):  # noqa: N802
        if self.path == "/x.osm.pbf":
            self.send_response(307)
            self.send_header("Location", "/mirror/x.osm.pbf")
            self.end_headers()
        elif self.path == "/mirror/x.osm.pbf":
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.payload)))
            self.end_headers()
            self.wfile.write(self.payload)
        elif self.path == "/x.osm.pbf.md5":
            self.send_response(302)
            self.send_header("Location", "/mirror/x.osm.pbf.md5")
            self.end_headers()
        elif self.path == "/mirror/x.osm.pbf.md5":
            body = f"{hashlib.md5(self.payload).hexdigest()}  x.osm.pbf\n".encode()  # noqa: S324
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def test_geofabrik_download_follows_redirects(tmp_path):
    from leadradar.modules.discovery import geofabrik

    # The egress policy only allows the dedicated test fixture port.
    srv = ThreadingHTTPServer(("127.0.0.1", int(os.environ["LEADRADAR_TEST_FIXTURE_PORT"])), _Redirecting)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        ext = geofabrik.Extract(id="t/x", name="x", parent=None, pbf_url=f"http://127.0.0.1:{srv.server_port}/x.osm.pbf",
                                iso2=["IS"], iso3166_2=[], size=len(_Redirecting.payload))
        path = geofabrik.download(ext, str(tmp_path))
        assert open(path, "rb").read() == _Redirecting.payload
    finally:
        srv.shutdown()
        srv.server_close()
