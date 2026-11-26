# LeadRadar

LeadRadar is a self-hosted platform for finding businesses, auditing their digital presence, scoring them as leads, and managing them in a CRM. It is rule-based and bilingual (English and Turkish), and it uses no AI services.

It discovers businesses from OpenStreetMap (Geofabrik extracts), audits their websites (HTTP checks, Playwright, Lighthouse, axe-core), detects tracking technologies, and records advertising research from official transparency sources. Every audit gets an administrator review. Lead, service and confidence scores are explainable and versioned. A lightweight CRM manages the pipeline, and sanitized client reports can be published with PDF export.

## Repository layout

```text
apps/api/        Python package `leadradar` (FastAPI API, workers, modules, Alembic migrations, tests)
  leadradar/modules/discovery       Geofabrik + PyOsmium extraction, industry matching, CSV import
  leadradar/modules/website_audit   HTTP stage, static HTML checks, Playwright, Lighthouse, tracking
  leadradar/modules/advertising     Independent providers (meta, google, linkedin, tiktok, microsoft, openai) + Apify
  leadradar/modules/scoring         Deterministic scoring engine and signal collection
  leadradar/modules/reporting       Sanitized report builder, HTML/PDF renderer, publication
  leadradar/modules/crm             Companies, dedupe/merge, suppression, filters, monitoring, maintenance
  leadradar/modules/netsafe         SSRF policy and egress filtering proxy
  leadradar/jobs                    PostgreSQL job queue, worker runtime, scheduler
apps/web/        Next.js admin interface (same-origin proxy to the API)
infrastructure/docker/   Dockerfiles (web; api/discovery/analysis targets)
docs/            Architecture, deployment, scoring, security, providers, limitations, implementation plan
scripts/         Secret generation, country catalog generator
tests/e2e/       Browser smoke test against a running stack
compose.yml      Dokploy-compatible Compose file (PostgreSQL is a separate Dokploy service)
```

## Quick start (development)

Requirements: Python 3.13, Node.js 22 and PostgreSQL 16 (PostGIS is optional and not required).

```bash
cd apps/api && python -m venv .venv && . .venv/bin/activate
pip install -e ".[discovery,analysis,dev]"
export DATABASE_URL=postgresql://postgres@127.0.0.1:5432/leadradar APP_ENV=development
eval "$(../../scripts/generate-secrets.sh | grep -v '^#' | sed 's/^/export /')"
python -m leadradar.cli migrate          # migrations + idempotent seeds + schedules the initial import once
python -m leadradar.cli create-admin     # interactive; there is no public registration
python -m leadradar.cli serve --port 8000
python -m leadradar.cli worker analysis  # and, in another shell: worker discovery
cd ../web && npm ci && API_INTERNAL_URL=http://127.0.0.1:8000 npm run dev
```

Open http://localhost:3000.

## Tests

```bash
cd apps/api && TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/leadradar_test python -m pytest
cd apps/web && npm run check:i18n && npm run lint && npm run typecheck
BASE_URL=http://127.0.0.1:3000 E2E_EMAIL=... E2E_PASSWORD=... node tests/e2e/smoke.mjs
```

## Deployment

See [docs/deployment-dokploy.md](docs/deployment-dokploy.md). The application has no configured domain: assign and change it in Dokploy, and no rebuild is needed.

## Documentation

- [Architecture and decisions](docs/architecture.md)
- [Deployment on Dokploy, backups, upgrades and recovery](docs/deployment-dokploy.md)
- [Security model](docs/security.md)
- [Scoring methodology](docs/scoring.md)
- [Advertising providers: access verification](docs/advertising-providers.md)
- [Data sources, OpenStreetMap licensing and limitations](docs/data-and-limitations.md)
- [Implementation plan and status](docs/implementation-plan.md)

## Licensing and attribution

- Map data © OpenStreetMap contributors, available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/). The attribution appears in the application and in reports that contain OSM-derived data.
- Geist fonts: SIL Open Font License 1.1 (`apps/api/leadradar/templates/fonts/OFL-Geist.txt`, and the `geist` npm package).
- Country flags: `flag-icons` (MIT). They are copied into `public/flags` at install time with their license.
- Country catalog: ISO 3166 data with Turkish names from the iso-codes project, via `pycountry` (LGPL-2.1). This is used only by the generator script; the generated JSON is committed.
