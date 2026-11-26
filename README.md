<p align="right">
  <strong>Language:</strong> English · <a href="README.tr.md">Türkçe</a>
</p>

# LeadRadar

LeadRadar is a self-hosted platform for finding potential clients, auditing their digital presence, scoring them as leads, and managing them in a CRM. It is built for agencies and freelancers who sell web design, digital marketing, advertising and related services.

LeadRadar is **rule-based**: it uses no AI, LLMs or AI APIs. Every automated result is deterministic, evidence-based and reproducible. The whole interface is available in **English and Turkish**.

> **Installation:** follow the step-by-step guide → **[Installing on Dokploy (English)](docs/deployment-dokploy.md)** · [Dokploy kurulumu (Türkçe)](docs/deployment-dokploy.tr.md)

---

## What it does

- **Discovery:** imports businesses from OpenStreetMap (Geofabrik extracts) for selected countries and industries. Companies can also be added by hand, from a website URL (Quick Audit), from a CSV file, or through the optional Apify integration.
- **Website audit:** HTTP and TLS checks, SEO, conversion and contact checks, broken links and images, Playwright screenshots (mobile and desktop), deterministic visual checks, axe-core accessibility, and Lighthouse lab performance.
- **Tracking detection:** Google Tag Manager, GA4, Google Ads, Meta Pixel, LinkedIn, TikTok, Microsoft UET, Clarity, Hotjar and consent platforms. Each result records its uncertainty: "not detected" is never treated as proof that tracking is absent.
- **Advertising research:** independent providers for Meta, Google, LinkedIn, TikTok, Microsoft and ChatGPT. Only official sources are used; where automation isn't permitted, the provider is marked Unsupported and offers a manual research link. Results are never fabricated.
- **Administrator review:** every full audit stops at *Action Required* until you answer the review questions. Subjective judgments such as design quality or branding are never made automatically.
- **Scoring:** explainable lead, confidence and service opportunity scores, with configurable scoring profiles and manual overrides.
- **CRM:** company table with server-side filters, tags, saved filters, a Kanban pipeline, activity timeline and follow-ups. A system-wide Do Not Contact list stays in effect after re-imports.
- **Client reports:** private drafts, administrator approval, and public links that can be revoked, password-protected or set to expire, in live or snapshot mode. PDF export in English and Turkish.
- **Operations:** a persistent PostgreSQL job queue (work continues after you close the browser), monitoring and change detection, retention policies, notifications, a health page, and a cost tracker.

## Architecture at a glance

| Service | Purpose |
|---|---|
| `web` | Next.js admin interface. It is the only public service and forwards `/api` and `/r` to the API on the same origin. |
| `api` | FastAPI REST API and public report pages. It runs database migrations on start. |
| `discovery-worker` | Geofabrik imports, CSV/Apify imports, campaigns, retention, scheduler. |
| `analysis-worker` | Website audits (Chromium, Lighthouse, axe-core), ad research, PDF generation. |
| PostgreSQL | A separate Dokploy database service that stores all data, including the job queue. |

No domain is configured in the code or in environment variables. You assign the domain in Dokploy and can change it at any time without rebuilding.

More detail: [docs/architecture.md](docs/architecture.md)

## Requirements

**Production (recommended):**
- A Linux server (Ubuntu 24.04 tested) with at least 4 vCPU, 6 GB RAM and 40 GB of free disk
- [Dokploy](https://dokploy.com) installed on the server
- A domain name, or a subdomain, pointing to the server
- A GitHub account with access to this repository

**Local development:**
- Python 3.13, Node.js 22 and PostgreSQL 16

## Installation

The full step-by-step guide covers creating the project, the database, the application, the environment variables, the domain, HTTPS, the first administrator, backups and updates:

- **English:** [docs/deployment-dokploy.md](docs/deployment-dokploy.md)
- **Türkçe:** [docs/deployment-dokploy.tr.md](docs/deployment-dokploy.tr.md)

## Local development

```bash
# 1. Backend
cd apps/api
python -m venv .venv && . .venv/bin/activate
pip install -e ".[discovery,analysis,dev]"
python -m playwright install chromium
export DATABASE_URL=postgresql://postgres@127.0.0.1:5432/leadradar
export APP_ENV=development
export $(../../scripts/generate-secrets.sh | grep -v '^#' | grep -v POSTGRES | xargs)
python -m leadradar.cli migrate        # creates tables and default data
python -m leadradar.cli create-admin   # creates your administrator account
python -m leadradar.cli serve --port 8000

# 2. Workers (separate terminals, same environment)
python -m leadradar.cli worker analysis
python -m leadradar.cli worker discovery   # note: starts the initial OSM imports

# 3. Frontend
cd apps/web
npm ci
API_INTERNAL_URL=http://127.0.0.1:8000 npm run dev
```

Then open http://localhost:3000.

## Tests

```bash
cd apps/api && TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/leadradar_test python -m pytest
cd apps/web && npm run check:i18n && npm run lint && npm run typecheck && npm run build
BASE_URL=http://127.0.0.1:3000 E2E_EMAIL=you@example.com E2E_PASSWORD=... node tests/e2e/smoke.mjs
```

## Repository layout

```text
apps/api/               Python package `leadradar`: API, workers, modules, migrations, tests
apps/web/               Next.js admin interface
infrastructure/docker/  Dockerfiles (web; api / discovery / analysis targets)
docs/                   Installation, architecture, security, scoring, providers, limitations
scripts/                Secret generator, country catalog generator
tests/e2e/              Browser smoke test
compose.yml             Dokploy-compatible Compose file (PostgreSQL is a separate service)
.env.example            Environment variable template
```

## Documentation

| Document | Content |
|---|---|
| [Installing on Dokploy](docs/deployment-dokploy.md) · [Türkçe](docs/deployment-dokploy.tr.md) | Step-by-step installation, domain changes, updates, backups, recovery |
| [Architecture](docs/architecture.md) | Services, data flow, job queue, design decisions |
| [Security](docs/security.md) | Authentication, CSRF, SSRF protection, public report safety |
| [Scoring](docs/scoring.md) | How lead, confidence and service scores are calculated |
| [Advertising providers](docs/advertising-providers.md) | What each ad platform allows and why |
| [Data and limitations](docs/data-and-limitations.md) | OpenStreetMap coverage, licensing, privacy, storage |
| [Implementation status](docs/implementation-plan.md) | What is tested, what still needs verification |

## Important notes

- LeadRadar never sends emails or messages, and never submits forms on audited websites.
- Publicly available contact information is not permission to send marketing. The Do Not Contact features support privacy management but do not by themselves guarantee GDPR or KVKK compliance.
- `robots.txt` and `noindex` keep the application out of search engines but are **not** access control; every private page requires login.

## Licensing and attribution

- Map data © OpenStreetMap contributors, under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/). The attribution appears in the application and in reports that contain OSM-derived data.
- Geist fonts: SIL Open Font License 1.1.
- Country flags: [flag-icons](https://github.com/lipis/flag-icons) (MIT).
- Country names: the iso-codes project via `pycountry` (LGPL-2.1), used only by the generator script.
