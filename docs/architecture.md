# Architecture

## Services

| Service | Image target | Role | Default limits |
|---|---|---|---|
| `web` | `web.Dockerfile` | Next.js admin UI, robots.txt, same-origin reverse proxy for `/api/*` and `/r/*` | 1 CPU / 384 MB |
| `api` | `api.Dockerfile:api` | FastAPI REST API, public report pages (`/r/{token}`), migrations on start | 1 CPU / 512 MB |
| `discovery-worker` | `api.Dockerfile:discovery` | Geofabrik downloads, PyOsmium extraction, CSV/Apify imports, campaigns, retention, score recalculation, **scheduler** | 1.5 CPU / 1.5 GB |
| `analysis-worker` | `api.Dockerfile:analysis` | Website audits (HTTP, Playwright/Chromium, Lighthouse, axe-core), ad research, PDF rendering, monitoring | 2 CPU / 2 GB |
| PostgreSQL | separate Dokploy database service | All state, including the job queue and bounded evidence storage | managed by Dokploy |

Total default limits are about 5.5 CPU and 4.4 GB, which fits the 4 vCPU / 6 GB VDS because limits are ceilings, not reservations. Heavy work is serialized by the global heavy-task limit (default 1).

Only `web` is routed publicly. The browser talks to one origin: `/api/*` and `/r/*` are proxied by a Next.js route handler to `API_INTERNAL_URL`, which is an internal Docker service name and never a public domain.

## Key decisions and deviations from the brief

1. **One Python package for the API and workers.** The brief suggested top-level `modules/` and `workers/` folders. Python packaging works best with one importable package, so the modules live in `apps/api/leadradar/modules/*` and the worker entry points in `leadradar/workers/`. The three Python images are build targets of one Dockerfile and share dependency layers.
2. **Alembic lives at `apps/api/migrations`** (not `database/migrations`) so it ships inside the API image. Seeds live in `leadradar/seeds`.
3. **PostGIS is not required.** Discovery needs only bounding-box proximity queries, which use B-tree indexes on latitude and longitude. This keeps the database service a stock PostgreSQL. `pg_trgm` is enabled when available.
4. **The scheduler is embedded in the discovery worker.** A session-level `pg_try_advisory_lock` guarantees a single active scheduler, so there is no separate service.
5. **Public report pages are rendered by the API with Jinja2.** One template serves the web view and the print/PDF view, so the redaction rules can't drift apart. Next.js proxies `/r/*` unchanged.
6. **PDFs are generated once per approved version and language** by the analysis worker, using Playwright with a self-contained document (fonts and images inlined, all network requests blocked). Public downloads serve the stored file, so a public request never launches a browser.
7. **Evidence storage is bounded in PostgreSQL** (`evidence_blobs`: compressed WebP screenshots and PDFs) with retention and pinning, so there is no mandatory volume or object store. The blob access is isolated in one table and helper, which allows a later migration to object storage.
8. **Egress filtering proxy.** Every outbound connection from workers goes through an in-process proxy that resolves DNS itself, rejects non-public addresses and disallowed ports, and connects to the validated IP. This covers HTTPX, Playwright, Lighthouse and provider calls, and defeats DNS rebinding. See [security.md](security.md).
9. **The `web` container is the only reverse-proxy hop to the API.** The API trusts `X-Forwarded-*` only from `TRUSTED_PROXIES` (Docker networks), and an optional administrator host allow-list further restricts accepted hosts.

## Data flow

```text
Geofabrik .osm.pbf ─► discovery worker (pass 1: KeyFilter → rule match; pass 2: IdFilter → way centroids)
                    ─► upsert_record (dedupe: source id → domain/phone/name+proximity) ─► companies (+suppression)
Company ─► create_audit ─► analysis worker: HTTP stage → static checks → Playwright (mobile+desktop, axe,
          screenshots, consent test) → Lighthouse → tracking detection → findings/evidence → preliminary score
          ─► Action Required (worker released) ─► administrator review ─► final score + recommendations
Advertising: per-provider job → official API (Meta, if a token is configured) or Unsupported + manual link
          → manual verified entries → advertiser match confirmation → score signals
Report: build sanitized content from allow-list → version (draft) → approve → PDF jobs → public token links
```

## Job queue

The `jobs` table is claimed with `FOR UPDATE SKIP LOCKED` inside a transaction that holds a per-queue advisory lock. That makes the global limits (heavy tasks, Geofabrik imports, light tasks) and the per-domain/company `concurrency_key` exclusivity atomic. Jobs have leases extended by heartbeats every 30 s, and the scheduler recovers expired leases every minute: requeued with exponential backoff, or dead-lettered after `max_attempts`. Idempotency keys prevent duplicate active jobs, such as the initial import, the same campaign, or a second audit of the same company. Progress is reported as processed counts, and a total is shown only when it is known.

Browser steps are not resumable mid-operation. An interrupted audit restarts as a whole. Imports checkpoint the processed count and re-run idempotent upserts.
