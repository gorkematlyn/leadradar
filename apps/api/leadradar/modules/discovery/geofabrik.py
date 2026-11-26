"""Geofabrik extract resolution and resumable, verified downloads.

Usage policy notes (https://download.geofabrik.de/): downloads are free; avoid
needlessly repeated downloads of the same file, avoid parallel downloads, and use
reasonable request rates. LeadRadar downloads one extract at a time, skips extracts
whose ``Last-Modified`` has not changed since the last import, and resumes partial
downloads with HTTP Range requests instead of starting over.
Data © OpenStreetMap contributors, ODbL 1.0.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx

from leadradar.modules.netsafe.http import make_client, safe_fetch

INDEX_PATH = "/index-v1-nogeom.json"


@dataclass
class Extract:
    id: str
    name: str
    parent: str | None
    pbf_url: str
    iso2: list[str]
    iso3166_2: list[str]
    size: int | None = None
    last_modified: datetime | None = None


class GeofabrikError(Exception):
    pass


def load_index(base_url: str) -> dict[str, Extract]:
    res = safe_fetch(base_url.rstrip("/") + INDEX_PATH, max_bytes=20_000_000, timeout=60)
    if res.status != 200:
        raise GeofabrikError(f"index download failed: {res.status} {res.error or ''}")
    return parse_index(json.loads(res.body))


def parse_index(data: dict) -> dict[str, Extract]:
    out: dict[str, Extract] = {}
    for feat in data.get("features", []):
        p = feat.get("properties", {})
        url = (p.get("urls") or {}).get("pbf")
        if not p.get("id") or not url:
            continue
        out[p["id"]] = Extract(
            id=p["id"], name=p.get("name", p["id"]), parent=p.get("parent"), pbf_url=url,
            iso2=[c.upper() for c in p.get("iso3166-1:alpha2", [])],
            iso3166_2=[c.upper() for c in p.get("iso3166-2", [])],
        )
    return out


def children_of(index: dict[str, Extract], extract_id: str) -> list[Extract]:
    return sorted((e for e in index.values() if e.parent == extract_id), key=lambda e: e.id)


def country_root(index: dict[str, Extract], iso2: str) -> Extract | None:
    """The top-most extract carrying this ISO code (e.g. 'us', 'germany', 'turkey')."""
    iso2 = iso2.upper()
    cands = [e for e in index.values() if iso2 in e.iso2]
    if not cands:
        return None
    tops = [e for e in cands if not (e.parent in index and iso2 in index[e.parent].iso2)]
    tops.sort(key=lambda e: (-len(children_of(index, e.id)), e.id))
    return tops[0] if tops else cands[0]


def head_info(extract: Extract) -> Extract:
    res = safe_fetch(extract.pbf_url, method="HEAD", timeout=30)
    if res.status == 200:
        if res.headers.get("content-length", "").isdigit():
            extract.size = int(res.headers["content-length"])
        if res.headers.get("last-modified"):
            try:
                extract.last_modified = parsedate_to_datetime(res.headers["last-modified"])
            except (TypeError, ValueError):
                pass
    return extract


def plan_extracts(
    index: dict[str, Extract], iso2: str, max_bytes: int, override_ids: list[str] | None = None,
    sizer: Callable[[Extract], Extract] = head_info,
) -> list[Extract]:
    """Choose manageable extracts covering a country (sub-regions for large countries)."""
    if override_ids:
        return [sizer(index[i]) for i in override_ids if i in index]
    root = country_root(index, iso2)
    if root is None:
        raise GeofabrikError(f"no Geofabrik extract for {iso2}")
    plan: list[Extract] = []
    stack = [root]
    while stack:
        ext = sizer(stack.pop(0))
        kids = children_of(index, ext.id)
        if ext.size is not None and ext.size > max_bytes and kids:
            stack = kids + stack
        else:
            plan.append(ext)
    return plan


def fetch_md5(url: str) -> str | None:
    res = safe_fetch(url + ".md5", max_bytes=4096, timeout=30)
    if res.status == 200 and res.body:
        token = res.body.decode("ascii", "ignore").split()[0] if res.body.split() else ""
        if len(token) == 32:
            return token.lower()
    return None


def check_disk(directory: str, needed_bytes: int, reserve_gb: int) -> None:
    os.makedirs(directory, exist_ok=True)
    free = shutil.disk_usage(directory).free
    if free - needed_bytes * 1.1 < reserve_gb * 1e9:
        raise GeofabrikError(
            f"insufficient disk space: free {free / 1e9:.1f} GB, need {needed_bytes / 1e9:.2f} GB + {reserve_gb} GB reserve"
        )


def download(
    extract: Extract,
    directory: str,
    *,
    progress: Callable[[int, int | None], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> str:
    """Download (resuming a ``.part`` file if present) and verify MD5. Returns the path."""
    os.makedirs(directory, exist_ok=True)
    final = os.path.join(directory, f"{extract.id.replace('/', '_')}.osm.pbf")
    part = final + ".part"
    if os.path.exists(final):
        os.remove(final)
    offset = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with make_client(timeout=120) as client:
        try:
            with client.stream("GET", extract.pbf_url, headers=headers) as resp:
                if resp.status_code == 416:  # already complete
                    pass
                elif resp.status_code == 200 and offset:
                    offset = 0  # server ignored Range; restart
                elif resp.status_code not in (200, 206):
                    raise GeofabrikError(f"download failed with HTTP {resp.status_code}")
                if resp.status_code in (200, 206):
                    mode = "ab" if resp.status_code == 206 else "wb"
                    written = offset
                    with open(part, mode) as fh:
                        for chunk in resp.iter_bytes(1 << 20):
                            fh.write(chunk)
                            written += len(chunk)
                            if progress:
                                progress(written, extract.size)
                            if should_stop and should_stop():
                                raise GeofabrikError("cancelled")
        except httpx.HTTPError as exc:
            raise GeofabrikError(f"download interrupted: {exc}") from exc
    expected = fetch_md5(extract.pbf_url)
    if expected:
        h = hashlib.md5()  # noqa: S324 - integrity check against Geofabrik's published MD5
        with open(part, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != expected:
            os.remove(part)
            raise GeofabrikError("MD5 checksum mismatch; partial file discarded")
    os.replace(part, final)
    return final


def cleanup_abandoned(directory: str, max_age_hours: float = 24) -> int:
    import time

    removed = 0
    if not os.path.isdir(directory):
        return 0
    for name in os.listdir(directory):
        if not name.endswith((".pbf", ".part")):
            continue
        path = os.path.join(directory, name)
        if time.time() - os.path.getmtime(path) > max_age_hours * 3600:
            os.remove(path)
            removed += 1
    return removed
