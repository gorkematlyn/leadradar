#!/usr/bin/env sh
# Prints fresh secrets for LeadRadar. Paste them into Dokploy's environment settings.
set -eu
python3 - <<'PY'
import base64, secrets
print("SESSION_SECRET=" + secrets.token_urlsafe(48))
print("APP_ENCRYPTION_KEY=" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
print("# Database password suggestion:")
print("POSTGRES_PASSWORD=" + secrets.token_urlsafe(24))
PY
