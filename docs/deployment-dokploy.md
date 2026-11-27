<p align="right">
  <strong>Language:</strong> English · <a href="deployment-dokploy.tr.md">Türkçe</a>
</p>

# Installing LeadRadar on Dokploy — step by step

This guide takes you from an empty server to a running LeadRadar with HTTPS and an administrator account. Follow the steps in order. Each step says **where** to click and **what** to enter.

> Dokploy's interface changes between versions, so a button may be labelled slightly differently. If a label doesn't match, look for the closest equivalent. The concepts (project, database service, compose service, environment, domains) stay the same.

← Back to the [README](../README.md)

---

## Overview

You will create:

1. One **project** in Dokploy, to group everything.
2. One **PostgreSQL database service**, which holds all LeadRadar data.
3. One **Compose service** from this GitHub repository, which runs four containers: `web`, `api`, `discovery-worker` and `analysis-worker`.
4. One **domain** assigned to the `web` container.

Estimated time: 30–45 minutes, most of it waiting for the first build.

---

## Part A — Preparation

### Step 1. Check the server
- Ubuntu 24.04 (or another Linux supported by Dokploy)
- At least **4 vCPU, 6 GB RAM, 40 GB free disk**. OpenStreetMap imports temporarily need several GB of disk; LeadRadar refuses to download when free space would drop below the reserve (15 GB by default).
- Ports **80** and **443** open to the internet.

### Step 2. Install Dokploy (skip if it is already installed)
Connect to the server over SSH and run the official installer:
```bash
curl -sSL https://dokploy.com/install.sh | sh
```
When it finishes, open `http://<server-ip>:3000` in your browser and create your Dokploy admin account.

> **Security tip:** after you assign Dokploy its own domain with HTTPS, close port 3000 in your firewall.

### Step 3. Point your domain at the server
At your DNS provider, create an **A record** (and an **AAAA** record if you use IPv6):

| Type | Name | Value |
|---|---|---|
| A | `leads` (for `leads.example.com`) or `@` | your server's public IP |

DNS can take a few minutes to propagate. Check it with `ping leads.example.com`.

### Step 4. Connect GitHub to Dokploy
1. In Dokploy, open **Settings → Git** (in some versions **Git Providers**).
2. Click **GitHub → Create GitHub App** and follow the prompts. GitHub asks you to confirm and install the app.
3. During installation, give the app access to the **LeadRadar repository** (or all repositories).
4. Back in Dokploy, the GitHub provider should be listed as connected.

### Step 5. Generate secrets
On your own computer (or on the server), in a copy of the repository:
```bash
./scripts/generate-secrets.sh
```
It prints three values:
```
SESSION_SECRET=...
APP_ENCRYPTION_KEY=...
POSTGRES_PASSWORD=...
```
**Save them in a password manager.** You need them in the next steps, and you need `APP_ENCRYPTION_KEY` again if you ever restore a backup.

If you don't have the repository locally, run this anywhere Python 3 is available:
```bash
python3 -c "import secrets,base64;print('SESSION_SECRET='+secrets.token_urlsafe(48));print('APP_ENCRYPTION_KEY='+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode());print('POSTGRES_PASSWORD='+secrets.token_urlsafe(24))"
```

---

## Part B — Create the project and the database

### Step 6. Create a project
1. In Dokploy, open **Projects**.
2. Click **Create Project**.
3. Name it `LeadRadar` and click **Create**.

### Step 7. Create the PostgreSQL database
1. Open the `LeadRadar` project.
2. Click **Create Service → Database**.
3. Choose **PostgreSQL**.
4. Fill in the form:

   | Field | Value |
   |---|---|
   | Name | `leadradar-db` |
   | Database Name | `leadradar` |
   | Database User | `leadradar` |
   | Database Password | the `POSTGRES_PASSWORD` from step 5 |
   | Docker Image | `postgres:16` (or newer) |

5. Click **Create**.
6. On the database page, click **Deploy** and wait until the status is **running**.
7. **Do not** set an external port; the database must stay internal.

### Step 8. Copy the internal connection URL
1. On the database page, find **Internal Credentials** (or **Internal Connection URL**).
2. Copy the **internal host** (it looks like `leadradar-db-abc123`) or the full internal URL.
3. Build your `DATABASE_URL` in this format:
   ```
   postgresql://leadradar:<POSTGRES_PASSWORD>@<internal-host>:5432/leadradar
   ```
   Example: `postgresql://leadradar:Xy7...@leadradar-db-abc123:5432/leadradar`

> If the password contains characters such as `@`, `:` or `/`, URL-encode them, or generate a password without them. Passwords from step 5 are URL-safe.

### Step 9. Enable database backups (recommended)
1. On the database page, open the **Backups** tab.
2. Add an S3-compatible destination (Dokploy **Settings → S3 Destinations** if none exists yet).
3. Schedule a daily backup, for example `0 3 * * *`.

The database holds **everything**: companies, CRM, evidence screenshots, reports and settings.

---

## Part C — Create and configure the application

### Step 10. Create the Compose service
1. In the `LeadRadar` project, click **Create Service → Compose**.
2. Name it `leadradar-app`.
3. Compose type: **Docker Compose**.
4. Click **Create**.

### Step 11. Connect the repository
1. Open `leadradar-app`, **General** tab.
2. Provider: **GitHub**.
3. Select the **repository** (LeadRadar) and the **branch** you want to deploy, for example `main`.
4. **Compose Path:** `./compose.yml`
5. Click **Save**.

### Step 12. Add the environment variables
1. Open the **Environment** tab.
2. Paste the following, replacing the values with yours:
   ```
   DATABASE_URL=postgresql://leadradar:<POSTGRES_PASSWORD>@<internal-host>:5432/leadradar
   SESSION_SECRET=<from step 5>
   APP_ENCRYPTION_KEY=<from step 5>
   APP_ENV=production
   LOG_LEVEL=INFO
   EGRESS_DENY_CIDRS=<your server's public IP>/32
   ```
3. Click **Save**.

What they mean:

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | Connection to the database from step 8 |
| `SESSION_SECRET` | yes | Signs sessions and public report tokens. Changing it signs everyone out and breaks shared report links. |
| `APP_ENCRYPTION_KEY` | yes | Encrypts stored provider tokens and 2FA secrets. **Never lose it.** |
| `EGRESS_DENY_CIDRS` | strongly recommended | Stops the audit browser from reaching your own server through its public IP, which protects the Dokploy panel. |
| `APP_ENV` | no | Keep `production`. |
| `TRUSTED_PROXIES` | no | Only change this if your Docker networks use unusual address ranges. |

There is **no domain variable**. The domain is set in step 14.

### Step 13. First deployment
1. Click **Deploy** at the top of `leadradar-app`.
2. Open the **Deployments** tab and click the running deployment to watch the logs.
3. The first build takes **10–20 minutes**, because it downloads Chromium, Lighthouse and the Python and Node dependencies. Later builds are faster thanks to caching.
4. When it finishes, open the **Logs** (or **Monitoring**) tab and choose each service:
   - `api` should show `migrations and seeds applied`, then request logs.
   - `discovery-worker` should show `starting worker` and `scheduler lock acquired`.
   - `analysis-worker` should show `starting worker`.

If the build fails, see [Troubleshooting](#troubleshooting).

---

## Part D — Domain and HTTPS

### Step 14. Assign the domain to the `web` service
1. In `leadradar-app`, open the **Domains** tab.
2. Click **Add Domain**.
3. Fill in the form:

   | Field | Value |
   |---|---|
   | Service Name | **`web`** (important: not `api`) |
   | Host | `leads.example.com` |
   | Path | `/` |
   | Container Port | **`3000`** |
   | HTTPS | **enabled** |
   | Certificate | **Let's Encrypt** |

4. Click **Create** (or **Save**).
5. Redeploy if Dokploy asks you to.

**Do not** add domains for `api`, `discovery-worker` or `analysis-worker`. The web container forwards `/api` and `/r` to the API internally.

### Step 15. Check that it works
1. Open `https://leads.example.com`. The certificate can take a minute to be issued.
2. You should see the **LeadRadar sign-in page**, with a message that no administrator exists yet.
3. Open `https://leads.example.com/robots.txt`. It should show `Disallow: /`.

---

## Part E — First use

### Step 16. Create the first administrator
Public registration doesn't exist; the administrator is created on the server.

**Option 1 — Dokploy terminal.** This guide was checked against Dokploy v0.31.4, where the terminal moved:
1. Open `leadradar-app` and go to its **Containers** tab (not Logs or Monitoring; those only show details).
2. Find the **`api`** container in the list.
3. Click the **three dots (⋯)** on its row and choose **Terminal**.
4. In the terminal, run:
```bash
cd /app
python -m leadradar.cli create-admin
```

> The terminal opens in `/`, not in `/app`. If you skip `cd /app` on an image built before the fix in step 16a, you get `No module named 'leadradar'`. Images built after that fix work from any directory.

**Option 2 — SSH.** Connect to the server and run:
```bash
docker ps --format '{{.Names}}' | grep api          # find the api container name
docker exec -it <api-container-name> python -m leadradar.cli create-admin   # starts in /app, no cd needed
```

Enter your email and a password with at least 12 characters, then confirm it. You'll see `administrator ... created`.

To add more administrators later, run the same command with `--additional`.

**Step 16a. Error `No module named 'leadradar'`?** You are in the wrong directory. Run `cd /app` first, then repeat the command. After you redeploy a version that contains `PYTHONPATH=/app` (commit "Docker: make leadradar importable from any directory"), the `cd` is no longer needed.

### Step 17. Sign in and secure your account
1. Sign in at `https://leads.example.com`.
2. Open **Settings → Account & security**.
3. Click **Enable 2FA**, scan the QR code with an authenticator app (Google Authenticator, 1Password, Aegis and others), and enter the code.
4. **Save the 10 recovery codes** somewhere safe. They are shown only once.

### Step 18. Review the settings
**Settings → General:**
- **Allowed hosts** (recommended): enter `leads.example.com`. Requests for any other host name are then rejected.
- **Public report origin** (optional): only if public reports should use a different domain.
- **Report branding**: your agency name and contact line.
- **Priority countries**, **Excluded domains**: adjust to your target market.

**Settings → Resources:** the defaults are conservative and suit 4 vCPU / 6 GB. Leave them as they are at first.

### Step 19. Check the initial imports
The first deployment automatically queued **one** import for each initial country: Türkiye, the Netherlands, Germany, the United Kingdom and the United States.
1. Open **Background Jobs**. You'll see `Country import` jobs that create child `Extract import` jobs.
2. Imports run **one at a time**. Large countries are split into regions, for example US states and German states, so a full import takes **several hours**.
3. On **Discovery** you can:
   - pause, cancel or retry imports,
   - enable or disable countries (disabling stops future imports and keeps existing companies),
   - start imports for more countries and industries.
4. Raw `.osm.pbf` files are deleted automatically after each extract.

### Step 20. Your first audit
1. Click **Quick Audit** in the top bar.
2. Enter a website address and choose **Full audit**.
3. The job appears in **Background Jobs**. When it finishes, the company shows **Action required**.
4. Open **Review Queue**, answer the review questions, validate the heuristic findings and approve screenshots for reports.
5. Click **Complete review**. The final score and recommendations are calculated.
6. From the company page, open the **Reports** tab, create a report, approve a version and create a public link.

You're done.

---

## Maintenance

### Updating LeadRadar
1. Back up the database first (step 9, or **Backups → Run now**).
2. Push the new code to the deployed branch, or click **Deploy** in `leadradar-app`.
3. Migrations run automatically when the `api` container starts. Several containers starting at once is safe because migrations take a database lock.
4. Check the `api` logs for `migrations and seeds applied`.

You can turn on automatic deploys on push in the **General** tab (Autodeploy). Only do this if you always back up before pushing.

### Changing the domain
1. Point the new domain's DNS at the server (step 3).
2. In `leadradar-app` → **Domains**, add the new domain for service `web`, port `3000`, with HTTPS.
3. In LeadRadar **Settings → General**, update **Allowed hosts** and, if set, **Public report origin**.
4. No rebuild or environment change is needed.
5. **Already shared report links point to the old domain.** Keep the old domain routed, or redirect it to the new one, for as long as those links should keep working.

### Manual backup and restore
Backup (on the server):
```bash
docker ps --format '{{.Names}}' | grep leadradar-db        # find the database container
docker exec <db-container> pg_dump -U leadradar -Fc leadradar > leadradar-$(date +%F).dump
```
Restore into an empty or existing database:
```bash
docker exec -i <db-container> pg_restore -U leadradar -d leadradar --clean --if-exists < leadradar-YYYY-MM-DD.dump
```
Keep `APP_ENCRYPTION_KEY` and `SESSION_SECRET` with your backups; restored data needs the same key.

### Recovering from a failed deployment

| Situation | What to do |
|---|---|
| The build failed | The previous containers keep running. Read the deployment log, fix the problem and deploy again. |
| `api` keeps restarting after an update | Check its logs. If a migration failed, deploy the previous commit or branch, and restore the backup if the database was changed. |
| A worker crashed during a job | Nothing to do. Its job lease expires and the job is requeued automatically within about 3 minutes. |
| Out of disk space | Delete old Docker images (`docker image prune`), lower screenshot retention under **Settings → Data retention**, and run cleanup. |

---

## Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| The page shows "Bad Gateway" or 502 | The domain points to the wrong service or port. It must be service `web`, port `3000`. |
| `No module named 'leadradar'` in the terminal | The terminal starts in `/`. Run `cd /app` and repeat the command. |
| "invalid_host" error | **Allowed hosts** doesn't include the domain you're using. Clear the list from the server: `docker exec -it <api> python -m leadradar.cli set-setting security.allowed_hosts '[]'` |
| `api` logs show "DATABASE_URL ... " or a connection refused error | Wrong internal host or password in `DATABASE_URL`, or the database service isn't running. |
| `APP_ENCRYPTION_KEY must decode to 32 bytes` | The key was copied incompletely. Generate a new one in the format from step 5. |
| Sign-in works but you're immediately logged out | You're using `http://` while `APP_ENV=production` sets secure cookies. Use `https://`. |
| Lost the 2FA device | Run `docker exec -it <api> python -m leadradar.cli reset-mfa you@example.com`, then use a recovery code or set up 2FA again. |
| Imports don't start | Check that `discovery-worker` is running and that the country is enabled on **Discovery**. Check free disk space; the default reserve is 15 GB. |
| Audits stay "Queued" | Check that `analysis-worker` is running. **Settings → System health** shows worker heartbeats. |

More information: [Architecture](architecture.md) · [Security](security.md) · [Data and limitations](data-and-limitations.md)

← Back to the [README](../README.md) · [Bu rehberin Türkçesi](deployment-dokploy.tr.md)
