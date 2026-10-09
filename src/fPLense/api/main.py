"""FPLense API (FastAPI). Run locally with ``uvicorn fPLense.api.main:app --reload``.

Reads ``data/published/`` only (loaded once, reloaded when files change), solves the squad ILP
and transfer planner on request, and proxies public FPL ``entry/*`` calls (cached, rate-limited).
It never runs the ETL, DuckDB or the model per request, and imports none of them (free hosts have
about 512 MB of RAM). OpenAPI docs at ``/docs``.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response

from fPLense import config, team_code
from fPLense.api.deps import TokenBucket
from fPLense.api.fpl_proxy import FplError, FplProxy
from fPLense.api.routers import codes, compare, entry, history, meta, players, squads, transfers
from fPLense.api.store import NotPublishedError, Store
from fPLense.api.views import BadRequest, NotFound
from fPLense.optimize.squad_ilp import InfeasibleSquadError

# GET responses built from published data get Cache-Control + ETag (not live FPL proxy calls)
UNCACHED_PREFIXES = ("/api/entry", "/api/health", "/docs", "/openapi.json", "/redoc")


def cors_origins() -> list[str]:
    raw = os.environ.get(config.API_CORS_ENV, config.API_CORS_DEFAULT)
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def create_app(
    published_dir: Path | str | None = None,
    proxy: FplProxy | None = None,
    origins: list[str] | None = None,
    rate_capacity: float = config.API_RATE_CAPACITY,
    rate_refill: float = config.API_RATE_REFILL_PER_S,
) -> FastAPI:
    published = published_dir or os.environ.get(config.API_PUBLISHED_ENV) or config.PUBLISHED_DIR

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await app.state.proxy.aclose()

    app = FastAPI(
        title="FPLense API",
        version="1.0.0",
        summary="FPL points forecasts, squad optimizer, season replay and team tools.",
        description=(
            "Prices are integer tenths of £1m (55 = £5.5m). Expected points come from a LightGBM "
            "model validated walk-forward; hindsight-best squads are the best legal £100m squads "
            "on actual points (not FPL's Dream Team). Not affiliated with the Premier League."
        ),
        lifespan=lifespan,
    )
    app.state.store = Store(published)
    app.state.proxy = proxy or FplProxy()
    app.state.limiter = TokenBucket(rate_capacity, rate_refill)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins is not None else cors_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "If-None-Match"],
        expose_headers=["ETag", "Retry-After"],
    )

    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def cache_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if (
            request.method != "GET"
            or response.status_code != 200
            or not path.startswith("/api/")
            or path.startswith(UNCACHED_PREFIXES)
        ):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        etag = '"' + hashlib.sha1(body).hexdigest() + '"'
        headers = dict(response.headers)
        headers["ETag"] = etag
        headers["Cache-Control"] = f"public, max-age={config.API_CACHE_MAX_AGE_S}"
        if request.headers.get("if-none-match") == etag:
            headers.pop("content-length", None)
            return Response(status_code=304, headers=headers)
        return Response(content=body, status_code=200, headers=headers)

    def error(status: int, detail: str, kind: str | None = None, headers=None):
        return JSONResponse({"detail": detail, "kind": kind}, status_code=status, headers=headers)

    @app.exception_handler(NotPublishedError)
    async def _not_published(_, exc):
        return error(503, str(exc), "not_published")

    @app.exception_handler(NotFound)
    async def _not_found(_, exc):
        return error(404, str(exc), "not_found")

    @app.exception_handler(BadRequest)
    async def _bad(_, exc):
        return error(422, str(exc), exc.kind)

    @app.exception_handler(InfeasibleSquadError)
    async def _infeasible(_, exc):
        return error(422, str(exc), exc.cause)

    @app.exception_handler(team_code.TeamCodeError)
    async def _code(_, exc):
        return error(422, exc.message, exc.kind)

    @app.exception_handler(FplError)
    async def _fpl(_, exc):
        headers = {"Retry-After": "60"} if exc.status == 503 else None
        return error(exc.status, str(exc), exc.__class__.__name__, headers)

    for module in (meta, players, squads, history, entry, transfers, compare, codes):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
