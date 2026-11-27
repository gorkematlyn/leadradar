# syntax=docker/dockerfile:1.7
# Python image shared by the API and both workers (targets: api, discovery, analysis).
ARG PYTHON_IMAGE=python:3.13-slim-bookworm
ARG NODE_IMAGE=node:22-bookworm-slim

FROM ${PYTHON_IMAGE} AS python-base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /app --shell /usr/sbin/nologin app
WORKDIR /app

# Dependencies first for layer caching.
COPY apps/api/pyproject.toml /tmp/build/pyproject.toml
RUN python - <<'PY' > /tmp/build/requirements.txt
import tomllib
p = tomllib.load(open("/tmp/build/pyproject.toml", "rb"))["project"]
print("\n".join(p["dependencies"]))
for extra in ("discovery", "analysis"):
    print("\n".join(p["optional-dependencies"][extra]), file=open(f"/tmp/build/{extra}.txt", "w"))
PY
RUN pip install -r /tmp/build/requirements.txt

# ---------------------------------------------------------------------------
FROM python-base AS api
COPY --chown=app:app apps/api/ /app/
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
# Migrations are advisory-locked, so concurrent container starts are safe.
CMD ["sh", "-c", "python -m leadradar.cli migrate && exec python -m leadradar.cli serve --host 0.0.0.0 --port 8000"]

# ---------------------------------------------------------------------------
FROM python-base AS discovery
# pyosmium (OSM parser) links against the system expat library, which the slim base image lacks.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
 && rm -rf /var/lib/apt/lists/*
RUN pip install -r /tmp/build/discovery.txt \
 && python -c "import osmium, osmium.osm; print('pyosmium', osmium.__version__ if hasattr(osmium, '__version__') else 'ok')"
COPY --chown=app:app apps/api/ /app/
RUN mkdir -p /tmp/leadradar && chown app:app /tmp/leadradar
USER app
ENV WORKER_QUEUES=discovery WORKER_CONCURRENCY=2 WORKER_TMP_DIR=/tmp/leadradar
CMD ["python", "-m", "leadradar.cli", "worker"]

# ---------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS node-tools
WORKDIR /opt/tools
RUN npm install --omit=dev --no-audit --no-fund lighthouse@13.6.0 axe-core@4.14.1 && npm cache clean --force

FROM python-base AS analysis
# Playwright's bundled Node needs libatomic, which the slim base image lacks.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
 && rm -rf /var/lib/apt/lists/*
RUN pip install -r /tmp/build/analysis.txt \
 && PLAYWRIGHT_BROWSERS_PATH=/ms-playwright python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
COPY --from=node-tools /usr/local/bin/node /usr/local/bin/node
COPY --from=node-tools /opt/tools /opt/tools
RUN ln -s /opt/tools/node_modules/lighthouse/cli/index.js /usr/local/bin/lighthouse
COPY --chown=app:app apps/api/ /app/
RUN mkdir -p /tmp/leadradar && chown app:app /tmp/leadradar
USER app
ENV WORKER_QUEUES=analysis WORKER_CONCURRENCY=2 WORKER_TMP_DIR=/tmp/leadradar \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright AXE_CORE_PATH=/opt/tools/node_modules/axe-core/axe.min.js \
    LIGHTHOUSE_BIN=/usr/local/bin/lighthouse
CMD ["python", "-m", "leadradar.cli", "worker"]
