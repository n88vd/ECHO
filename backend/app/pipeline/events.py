import logging
import time
from contextlib import asynccontextmanager

from app.core.db import pool
from app.core.logging import log

logger = logging.getLogger("echo.pipeline")


@asynccontextmanager
async def stage_event(stage: str, subject_type: str, subject_id: str, user_id: str | None, attempt: int = 1, version: int = 1):
    t0 = time.perf_counter()
    meta: dict = {}
    try:
        yield meta
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        await pool().execute(
            """insert into echo.processing_events(user_id, subject_type, subject_id, stage, stage_version, status, attempt, duration_ms, error, meta)
               values ($1,$2,$3,$4,$5,'failed',$6,$7,$8,$9)""",
            user_id, subject_type, subject_id, stage, version, attempt, ms, str(e)[:1000], meta,
        )
        log(logger, logging.WARNING, "stage failed", stage=stage, subject_id=subject_id, error=str(e)[:300])
        raise
    ms = int((time.perf_counter() - t0) * 1000)
    status = meta.pop("_status", "succeeded")
    await pool().execute(
        """insert into echo.processing_events(user_id, subject_type, subject_id, stage, stage_version, status, attempt, duration_ms, meta)
           values ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
        user_id, subject_type, subject_id, stage, version, status, attempt, ms, meta,
    )
    log(logger, logging.INFO, "stage done", stage=stage, subject_id=subject_id, status=status, ms=ms)
