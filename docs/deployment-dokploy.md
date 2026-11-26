# Deploying LeadRadar on Dokploy

This guide assumes a Dokploy server (Ubuntu 24.04, 4 vCPU, 6 GB RAM) and that the repository is on GitHub. Nothing is pushed or deployed automatically.

## 1. Create the PostgreSQL service
In Dokploy, go to **Create service → Database → PostgreSQL** (version 16 or later), named for example `leadradar-db`. Use a strong password (`scripts/generate-secrets.sh` prints one). Do not expose an external port.

## 2. Database persistence
Dokploy database services keep their data in their own Docker volume, independent of the application. Leave persistence enabled. The application containers are stateless.

## 3. Database extensions
None are required. The first migration tries `CREATE EXTENSION IF NOT EXISTS pg_trgm` and continues without it if the role lacks permission.

## 4. Connect the repository
Go to **Create service → Compose**, connect the GitHub repository and branch, and set the Compose path to `compose.yml`.

## 5. Environment secrets
In the Compose service's **Environment** tab, set:
```
DATABASE_URL=postgresql://<user>:<password>@<internal-db-host>:5432/<db>
SESSION_SECRET=<from scripts/generate-secrets.sh>
APP_ENCRYPTION_KEY=<from scripts/generate-secrets.sh>
EGRESS_DENY_CIDRS=<this server's public IP>/32
```
Keep `APP_ENCRYPTION_KEY` safe. Losing it makes stored provider tokens and TOTP secrets unreadable. Changing `SESSION_SECRET` invalidates sessions and all public report links. No domain variable exists or is needed.

## 6. Deploy
Click **Deploy**. Dokploy builds four images (web, api, discovery-worker, analysis-worker). The `api` container runs `migrate` (advisory-locked) before serving. Migrations, idempotent seeds (countries, industries, rules, profiles, statuses, templates, settings) and the one-time scheduling of the initial imports happen there.

## 7. Assign the domain
In **Domains**, add your domain to the **web** service on port **3000**. Do not route the API or the workers.

## 8. HTTPS
Enable HTTPS with Let's Encrypt in the domain settings. TLS ends at Dokploy's Traefik. Cookies are marked `Secure` in production.

## 9. Migrations
These run automatically on every `api` start. To run them manually: **api → Terminal**, then `python -m leadradar.cli migrate`.

## 10. Create the first administrator
**api → Terminal**:
```
python -m leadradar.cli create-admin
```
Public registration does not exist. To add more administrators, run the same command with `--additional`. If an account loses its 2FA device, run `python -m leadradar.cli reset-mfa <email>`.

## 11. Initial Geofabrik imports
Imports for TR, NL, DE, GB and US are queued once at first migration and run one extract at a time. Large countries are split into sub-regions; the size threshold is configurable. You can pause, cancel or retry them on **Background Jobs**, and change countries or industries on **Discovery**. Raw `.osm.pbf` files are deleted after each extract is processed. Keep at least the configured disk reserve free (15 GB by default). The worker refuses a download that would go below it.

## 12. Monitoring
**Background Jobs** shows live progress, heartbeats, logs and retry and cancel actions. **Settings → System health** shows CPU, memory, disk, database size, worker heartbeats and recent errors. Notifications appear in the bell menu.

## 13. Changing the domain
Add the new domain to the `web` service in Dokploy. No rebuild or environment change is needed. If you configured **Settings → General → Allowed hosts** or **Public report origin**, update them too. Previously shared absolute report links keep working only if the old domain stays routed or redirects to the new one.

## 14. Updating
Pull the new code (push to the tracked branch, or click **Deploy**). Migrations run on start. Back up the database first (step 15). Migrations are additive by default; any destructive migration will be called out in its file and in release notes.

## 15. Backup and restore
Dokploy can schedule PostgreSQL backups to S3-compatible storage (**Database → Backups**). For a manual backup:
```
docker exec <db-container> pg_dump -U <user> -Fc <db> > leadradar-$(date +%F).dump
```
To restore into an empty database:
```
docker exec -i <db-container> pg_restore -U <user> -d <db> --clean --if-exists < leadradar-YYYY-MM-DD.dump
```
The database holds everything: companies, CRM, evidence screenshots, report PDFs and settings. Back up `APP_ENCRYPTION_KEY` and `SESSION_SECRET` separately.

## 16. Recovering from a failed deployment
- If a build failed, the previous containers keep running. Fix the build and redeploy.
- If a migration failed, the `api` container exits and the old version is no longer serving. Roll back by deploying the previous commit; Alembic downgrades are available for development only. Restore the backup from step 15 if the schema is inconsistent.
- If workers crashed mid-job, nothing is needed: leases expire and the scheduler requeues the jobs within about 3 minutes.

## Optional private-network access
To make the admin UI reachable only over WireGuard or Tailscale, do not assign a public domain. Expose the `web` service on the VPN interface, or use Dokploy's domain with an IP allow-list middleware. Public reports then need a separate public route for `/r/*`. Neither VPN is required.

## Resource notes
The defaults are conservative (1 heavy browser task, 1 import, 5 light tasks) and can be changed in **Settings → Resources**. The analysis worker uses `shm_size: 512m` for Chromium. Validate with real measurements after deployment, for example `docker stats` during an import and an audit.
