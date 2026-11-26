# Data sources, licensing and limitations

## OpenStreetMap / Geofabrik
- **Source:** regional extracts from `download.geofabrik.de`, resolved through `index-v1-nogeom.json`. The importer picks the top-level extract for the country's ISO code. If its size (from HTTP `Content-Length`) exceeds the configured maximum (1.2 GB by default), it recurses into sub-regions, so the United States uses states and Germany uses Länder.
- **Usage policy:** one download at a time, an HTTP Range resume of `.part` files after interruptions, MD5 verification against Geofabrik's published `.md5` files, and no re-download of extracts whose `Last-Modified` has not changed within the configured window (7 days by default).
- **Licence:** data is © OpenStreetMap contributors under ODbL 1.0. The attribution appears in the app footer and in reports that contain OSM-derived data. Only business-relevant attributes are stored (name, address, contact tags, a coordinate and the matching tags). Roads, landuse and other geometry are never imported.
- **Processing:** two passes with PyOsmium. Pass 1 uses a C++ `KeyFilter` on rule keys and matches industry rules in Python. Pass 2 resolves only the node coordinates referenced by matching ways, through an `IdFilter`. Memory therefore scales with the number of matching businesses, not with the size of the extract.
- **Coverage limitations:**
  - Multipolygon relations are not imported. Most businesses are mapped as nodes or closed ways.
  - OSM coverage of websites, emails and phones is incomplete and varies by country. A missing `website` tag gives *Website not found*, never *No website*. Only a manual verification marks a website as absent.
  - Tags cannot prove "boutique" hotels, "aesthetic" clinics (dermatology) or "B2B suitability" (industrial works). Those matches are stored as **review candidates**, and branded hotel chains are excluded by the `brand` tags.
  - E-commerce brands have no OSM rule, and digital agencies have only an uncertain one. Use CSV import, Quick Audit, manual entry or the optional Apify provider for them.
  - Branches that share a domain are not merged automatically. They link to the same web property, so the audit is reused, and they appear in the duplicate review queue.

## Country catalog
There are 250 countries and territories (ISO 3166-1, plus Kosovo) with English and Turkish names. Regions follow the UN M49 continents, with the Americas split into North America (including Central America and the Caribbean) and South America, and a separate Antarctica region. Flags are self-hosted SVGs from `flag-icons`. The catalog is regenerated with `scripts/generate_country_catalog.py`.

## Website audit limitations
- Lighthouse figures are **laboratory** measurements under simulated mobile throttling. They are not CrUX field data or verified Core Web Vitals.
- Visual checks are deterministic DOM heuristics and are labelled as such until a reviewer confirms them. Aesthetics, logos, branding and creative quality are never judged automatically.
- Tracking detection is client-side observation only. *Not detected* is never treated as proof of absence, because tags may wait for consent, run server-side, or load conditionally or by region. Tracking IDs are stored only as redacted hashes.
- axe-core covers only part of WCAG.
- Sites that block automated clients get a `blocked` result. These checks earn no deficiency points.

## Privacy
Only business contact channels are collected: emails on the company's own domain, public phone numbers, and company pages on social networks. Personal LinkedIn profiles (`/in/…`) are ignored. Do Not Contact suppression applies system-wide by company, domain, email, phone and source ID, survives re-imports and deletions, and is applied to contact-oriented exports. Retention policies are configurable. **These features support privacy management but do not by themselves guarantee GDPR, KVKK or other legal compliance. Publicly available contact information is not permission for marketing communications.**

## Storage trade-offs
Evidence screenshots (WebP, capped at 450 KB by default) and report PDFs are kept in PostgreSQL to avoid a mandatory volume or object store. This increases database size and backup size. Watch it in **Settings → System health**, and shorten screenshot retention if needed. Evidence used by published reports or pending reviews is pinned and never deleted. Moving to object storage later only requires replacing the `EvidenceBlob` read and write helpers.
