"""FastAPI application. Served behind the web container at the same origin under /api.

No interactive API documentation is exposed (docs, redoc and openapi.json are disabled).
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from leadradar.api.routes import advertising, audits, auth, catalog, companies, reports, system
from leadradar.core.config import get_settings
from leadradar.core.logging import configure_logging, redact
from leadradar.db.session import get_sessionmaker

settings = get_settings()  # fails fast with a clear error on invalid configuration
configure_logging(settings.log_level)
log = logging.getLogger("leadradar.api")

app = FastAPI(title="LeadRadar", docs_url=None, redoc_url=None, openapi_url=None, swagger_ui_oauth2_redirect_url=None)

API_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
    "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


@app.middleware("http")
async def security_and_logging(request: Request, call_next):  # type: ignore[no-untyped-def]
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    started = time.monotonic()
    if int(request.headers.get("content-length") or 0) > 12 * 1024 * 1024:
        return JSONResponse({"detail": "payload_too_large"}, status_code=413)
    response = await call_next(request)
    for k, v in API_HEADERS.items():
        response.headers.setdefault(k, v)
    if not request.url.path.startswith("/r/"):
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        response.headers.setdefault("Cache-Control", "no-store")
    response.headers["X-Request-ID"] = rid
    log.info(
        "request",
        extra={"data": {"rid": rid, "method": request.method, "path": redact(request.url.path),
                        "status": response.status_code, "ms": int((time.monotonic() - started) * 1000)}},
    )
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()[:20]]
    return JSONResponse({"detail": "validation_error", "errors": errors}, status_code=422)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return JSONResponse({"detail": "internal_error"}, status_code=500)


@app.get("/api/health", include_in_schema=False)
def health() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/api/ready", include_in_schema=False)
def ready() -> PlainTextResponse:
    db = get_sessionmaker()()
    try:
        db.execute(text("SELECT 1"))
        return PlainTextResponse("ready")
    except Exception:
        return PlainTextResponse("database unavailable", status_code=503)
    finally:
        db.close()


for r in (auth.router, companies.router, catalog.router, audits.router, advertising.router, reports.router, system.router):
    app.include_router(r, prefix="/api")
app.include_router(reports.public)
