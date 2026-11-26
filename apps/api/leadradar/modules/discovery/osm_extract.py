"""Memory-efficient extraction of business POIs from an .osm.pbf file.

Pass 1 streams nodes and ways through a C++ ``KeyFilter`` (only objects carrying a
relevant key reach Python), matches industry rules, and records the node references
of matching ways in an ``IdTracker``.
Pass 2 streams only the referenced nodes (C++ ``IdFilter``) to compute way centroids.

No node-location index for the whole extract is built, so memory stays proportional to
the number of matching businesses. Multipolygon relations are not imported (documented
limitation; most businesses are mapped as nodes or closed ways).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from leadradar.modules.discovery.matching import CompiledRule, Match, match_industries, required_keys

KEEP_TAGS = {
    "name", "name:en", "name:tr", "official_name", "brand", "brand:wikidata", "operator", "website", "contact:website",
    "url", "email", "contact:email", "phone", "contact:phone", "contact:mobile", "contact:facebook",
    "contact:instagram", "contact:linkedin", "contact:twitter", "facebook", "instagram", "addr:street",
    "addr:housenumber", "addr:postcode", "addr:city", "addr:state", "addr:province", "addr:district",
    "addr:suburb", "addr:country", "opening_hours", "stars", "healthcare", "healthcare:speciality", "amenity",
    "shop", "office", "craft", "tourism", "man_made", "industrial", "company", "check_date", "disused:amenity",
    "disused:shop", "abandoned:amenity", "wheelchair", "cuisine", "rooms",
}


@dataclass
class ExtractedPoi:
    osm_type: str  # node / way
    osm_id: int
    tags: dict[str, str]
    lat: float | None
    lon: float | None
    matches: list[Match]
    timestamp: str | None = None
    node_refs: list[int] = field(default_factory=list)

    @property
    def source_key(self) -> str:
        return f"{self.osm_type}/{self.osm_id}"


def _kept(tags) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {t.k: t.v for t in tags if t.k in KEEP_TAGS or t.k.startswith(("disused:", "abandoned:"))}


def extract_pois(
    path: str,
    rules: list[CompiledRule],
    *,
    progress: Callable[[str, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[ExtractedPoi]:
    import osmium
    from osmium.filter import IdFilter, KeyFilter  # noqa: F401

    keys = required_keys(rules)
    if not keys:
        return
    tracker = osmium.IdTracker()
    pending_ways: list[ExtractedPoi] = []
    count = 0
    fp = osmium.FileProcessor(path, osmium.osm.NODE | osmium.osm.WAY).with_filter(KeyFilter(*sorted(keys)))
    for obj in fp:
        count += 1
        if progress and count % 50_000 == 0:
            progress("scan", count)
            if should_stop and should_stop():
                return
        if "name" not in obj.tags:
            continue
        tags = _kept(obj.tags)
        matches = match_industries(rules, tags)
        if not matches:
            continue
        ts = obj.timestamp.isoformat() if getattr(obj, "timestamp", None) else None
        if obj.is_node():
            loc = obj.location
            yield ExtractedPoi("node", obj.id, tags, loc.lat if loc.valid() else None,
                               loc.lon if loc.valid() else None, matches, ts)
        elif obj.is_way():
            refs = [n.ref for n in obj.nodes]
            if not refs:
                continue
            for r in refs:
                tracker.add_node(r)
            pending_ways.append(ExtractedPoi("way", obj.id, tags, None, None, matches, ts, refs))
    if not pending_ways:
        return
    if progress:
        progress("resolve_way_geometry", len(pending_ways))
    coords: dict[int, tuple[float, float]] = {}
    for node in osmium.FileProcessor(path, osmium.osm.NODE).with_filter(tracker.id_filter()):
        if node.location.valid():
            coords[node.id] = (node.location.lat, node.location.lon)
    for poi in pending_ways:
        pts = [coords[r] for r in poi.node_refs if r in coords]
        if pts:
            # Closed ways repeat the first node; mean of vertices is an adequate centroid for POIs.
            uniq = pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else pts
            poi.lat = sum(p[0] for p in uniq) / len(uniq)
            poi.lon = sum(p[1] for p in uniq) / len(uniq)
        poi.node_refs = []
        yield poi
