import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import routes_account, routes_ask, routes_auth, routes_ingest, routes_internal, routes_memory
from app.core.config import get_settings
from app.core.db import close_pool, init_pool
from app.core.logging import log, setup_logging
from app.providers.base import ProviderError

logger = logging.getLogger("echo.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(get_settings().log_level)
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="ECHO API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    if request.url.path not in ("/healthz",):
        log(logger, logging.INFO, "request", rid=rid, method=request.method, path=request.url.path,
            status=response.status_code, ms=int((time.perf_counter() - t0) * 1000),
            user_id=getattr(request.state, "user_id", None))
    return response


@app.exception_handler(ProviderError)
async def provider_error(_: Request, exc: ProviderError):
    return JSONResponse(status_code=503 if exc.retryable else 502, content={"detail": "upstream provider error"})


for r in (routes_internal, routes_auth, routes_ingest, routes_memory, routes_ask, routes_account):
    app.include_router(r.router)
