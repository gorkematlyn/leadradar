# Security model

## Authentication
- There is no public registration. The first administrator is created with `leadradar create-admin` on the server.
- Passwords are hashed with Argon2id (19 MiB, t=2, p=1) and rehashed transparently when the parameters change. The minimum length is 12. Login takes constant time whether or not the account exists.
- Sessions are server-side. Each uses a 256-bit random token stored as a keyed SHA-256 hash, sent in an `HttpOnly`, `SameSite=Lax` cookie with no `Domain` attribute (host-only), marked `Secure` under HTTPS or in production. Sessions have an absolute lifetime and an idle timeout (both configurable), and can be revoked individually or all at once ("log out from all devices"). Changing the password revokes all other sessions.
- TOTP two-factor authentication: the secret is Fernet-encrypted at rest, a used code cannot be replayed, and 10 single-use recovery codes are stored as Argon2 hashes. After the password step, a pending-MFA session grants no access.
- Brute-force protection: a per-IP fixed-window limit in PostgreSQL, plus per-account lockout after N failures (configurable). MFA attempts are rate-limited per user.
- Login, failed login, lockout, MFA changes, password changes, session revocation, exports, merges, suppression changes, settings changes and report publication are written to `activity_logs`.

## Request protection
- CSRF: the `Origin` (or `Referer`) header must match the validated request origin, and a double-submit token (a cookie plus the `X-CSRF-Token` header) must also match the hash stored on the session.
- Host header: `X-Forwarded-Host/Proto` is honoured only from `TRUSTED_PROXIES`. Hosts are validated syntactically, and an optional **allowed hosts** setting rejects everything else (HTTP 400).
- Authorization: every `/api/*` route except `auth/state`, login, MFA, `/api/health` and `/api/ready` requires a full session. Objects are always loaded by ID and checked for ownership where relevant, for example a report version's report or a finding's audit.
- Headers: a nonce-based CSP on the UI, `default-src 'none'` on API JSON, `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP/CORP. HSTS is set by Traefik/Dokploy once HTTPS is enabled; enable it there.
- Interactive API documentation (`/docs`, `/redoc`, `/openapi.json`) is disabled.
- Robots: `robots.txt` disallows everything, and `X-Robots-Tag: noindex, nofollow, noarchive, nosnippet` plus meta robots are applied everywhere, including public reports. **These do not provide access control**; authentication does.
- Uploads: CSV files are limited to 10 MB, decoded as text and parsed only. Exports neutralize spreadsheet formula injection. External HTML in evidence is sanitized with `nh3` and never executed. The admin UI never embeds external sites; screenshots are images served by the API.

## Outbound network safety (SSRF)
All worker traffic goes through `leadradar.modules.netsafe`:
- Only `http` and `https`, no credentials in URLs, and only allowed ports (`EGRESS_ALLOWED_PORTS`, default 80 and 443). This blocks Dokploy on 3000, PostgreSQL on 5432 and other internal ports.
- Hostnames that resolve to internal services (single-label names like `api` or `db`, and `.internal`, `.local` and similar) are rejected before DNS.
- DNS is resolved by the proxy itself. If **any** returned address is loopback, private, link-local, CGNAT, multicast, reserved, documentation, metadata (`169.254.169.254`) or in `EGRESS_DENY_CIDRS`, the request is refused. The proxy then connects to the validated IP, so the browser never resolves names itself and DNS rebinding is impossible. Every redirect hop is revalidated.
- Chromium runs with `--proxy-server` and `--proxy-bypass-list=<-loopback>`, so loopback is proxied and refused too. It uses one isolated context per viewport, with downloads cancelled, permissions empty and service workers blocked. Lighthouse uses the same proxy flags.
- Response sizes, redirects and timeouts are bounded, and each proxied connection has a byte budget.
- The only page interaction is an optional click on a known cookie-consent **accept** button, for the documented consent-state tracking test. Forms are never submitted and orders or contact actions are never triggered.
- Workers have no Docker socket, run as non-root with `no-new-privileges` and all capabilities dropped. **Chromium sandbox:** Docker's default seccomp profile does not allow Chromium's user-namespace sandbox without extra privileges, so Chromium runs with `--no-sandbox` by default. Isolation comes from the container, the non-root user, the dropped capabilities and the egress proxy. If your host allows unprivileged user namespaces, set `LEADRADAR_BROWSER_SANDBOX=1`.
- Add the server's public IP to `EGRESS_DENY_CIDRS` so an audited site cannot point the browser at your own Dokploy instance through a public address.

## Public reports
- Tokens are 256-bit random, stored as keyed hashes and shown once. They can be revoked, rotated, given an expiry, or protected with an Argon2-hashed password (unlock cookie scoped to `/r/`).
- Content comes from a separate, allow-listed data model (`report_versions.content`). Internal scores, confidence, CRM status, notes, tags, personal contact data, logs, raw tracking identifiers and infrastructure details are never copied into it. Integration tests check that internal data does not leak.
- Only approved versions are visible. A live link follows the latest approved version; a snapshot link stays pinned. New audits never change public content until a version is approved.
- Requests are rate-limited per IP. Request logs redact `/r/<token>` paths.

## Secrets
Only `SESSION_SECRET`, `APP_ENCRYPTION_KEY` and `DATABASE_URL` live in the environment. Provider tokens (Meta, Apify) are Fernet-encrypted in the database, write-only from the UI, and never returned to the frontend.
