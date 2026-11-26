# Implementation plan and status

The status column says how each item was verified in this release:
**Tested** means covered by automated tests (`apps/api/tests`, the i18n check, or `tests/e2e/smoke.mjs`). **Exercised** means run manually end-to-end against real components in development. **Not yet run** means implemented but not executed in the build environment; reasons are given in the notes.

## Phase 1 — Foundation
| Item | Status | Notes |
|---|---|---|
| Repository, Docker architecture, Compose | Implemented | Dockerfiles not built locally (no Docker daemon available); CI builds them. |
| Database, migrations, advisory-locked migrate | Tested | `alembic check` confirms the models match the migrations. |
| Authentication (Argon2id, sessions, TOTP, recovery codes, lockout, logout-all) | Tested | `test_auth_security.py` |
| CSRF, host-header validation, security headers, no API docs | Tested | |
| i18n (EN/TR, 943 keys, persisted per account) | Tested | `npm run check:i18n`; e2e checks that the language switch persists. |
| Themes (light/dark/system, persisted) | Tested | e2e |
| Design system, application shell | Exercised | Browser screenshots reviewed. |

## Phase 2 — Discovery and CRM
| Item | Status | Notes |
|---|---|---|
| Country catalog (250), regions, flags, 12 industries, OSM rules | Tested | Seeding is idempotent and preserves administrator customizations. |
| Geofabrik planning (sub-regions), resumable download, MD5, disk checks | Tested (planning) / Not yet run (live download) | The build network blocks `download.geofabrik.de`. |
| PyOsmium two-pass extraction | Tested | Runs on a generated `.pbf` fixture. |
| Initial import scheduled exactly once, pause/cancel/retry | Tested | |
| Persistent job queue (limits, concurrency keys, leases, recovery, dead letters) | Tested | |
| Dedupe, domain normalization, branches, merge, provenance | Tested | |
| CSV import with mapping, manual creation, Quick Audit | Tested / Exercised | |
| Tags (AND/OR/exclude), saved filters, CRM statuses, activities, Kanban | Tested / Exercised | |
| Do Not Contact suppression (survives re-import and deletion, export exclusion) | Tested | |

## Phase 3 — Website analysis
| Item | Status | Notes |
|---|---|---|
| HTTP stage, TLS, redirects, parked/maintenance, robots/sitemap, links/images | Tested | Runs against a local fixture site. |
| Static SEO, structure and conversion checks with industry relevance | Tested | |
| Playwright stage (mobile/desktop, visual heuristics, screenshots WebP, consent test) | Tested | Uses Chromium in integration tests when `CHROME_PATH` is set. |
| axe-core | Not yet run | Not installed in the build environment; installed in the analysis image. Missing axe yields `unknown`, not a failure. |
| Lighthouse | Tested (parser) / Not yet run (CLI) | The CLI is installed only in the analysis image. |
| Tracking detection with consent states and redacted IDs | Tested | |
| Evidence viewer, sanitized HTML | Exercised | |
| SSRF / egress proxy | Tested | |

## Phase 4 — Review and scoring
| Item | Status |
|---|---|
| Action Required workflow, worker released, review questions, finding validation | Tested |
| Preliminary/final/confidence/service scores, profiles, overrides, recalculation, profile preview | Tested |

## Phase 5 — Advertising intelligence
| Item | Status | Notes |
|---|---|---|
| Independent providers, manual research, match confirmation | Tested | |
| Meta Ad Library API | Tested (parser) / Not yet run (live) | Requires an administrator token. |
| Google, LinkedIn, TikTok, Microsoft, ChatGPT | Unsupported (documented) | See [advertising-providers.md](advertising-providers.md). |
| Apify with budgets and cost tracker | Implemented / Not yet run (live) | Budget checks block runs without configured limits. |

## Phase 6 — Reporting
| Item | Status |
|---|---|
| Sanitized versions, approval, live vs snapshot, password, expiry, revoke, rotate | Tested |
| No internal-data leakage on public pages | Tested |
| PDF (A4, page numbers, TR characters, inlined assets) | Tested (with Chromium) |

## Phase 7 — Automation and optimization
| Item | Status | Notes |
|---|---|---|
| Saved campaigns (manual and scheduled, no overlapping runs) | Implemented / Exercised (UI) | |
| Watchlists and change detection (noise-normalized) | Tested (diff logic) | |
| Retention cleanup with pinning, evidence storage budget | Implemented | |
| Notifications, health page, resource-aware claiming | Implemented / Exercised | |

## Phase 8 — Production readiness
| Item | Status | Notes |
|---|---|---|
| Unit, integration and security tests (95) | Passing | |
| Browser e2e smoke test | Passing | Run against a local stack. |
| CI (lint, types, tests, builds, Docker build, audits, gitleaks) | Implemented | Not yet run on GitHub. |
| Dokploy, backup and recovery documentation | Written | |
| Performance testing on the target VDS | Not yet run | Validate the resource defaults after first deployment. |

## Known gaps and next steps
1. Run the first Geofabrik imports on the server and record memory, time and disk use per extract, then adjust `geofabrik.max_extract_bytes`.
2. Verify Microsoft's Ad Library API parameters against Microsoft's documentation and implement the provider if its terms allow.
3. Columns can be reordered from the column menu (move left/right); drag-and-drop reordering is not implemented.
4. Multipolygon business relations from OSM are not imported.
5. A browser e2e test for the full audit → review → publish flow runs at the API level (`test_audit_review_report.py`); the UI smoke test covers navigation, CRUD, language and theme.
