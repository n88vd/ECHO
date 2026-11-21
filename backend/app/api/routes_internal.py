import hmac

from fastapi import APIRouter, HTTPException, Request

from app.core import queue
from app.core.config import get_settings
from app.core.db import pool

router = APIRouter(tags=["internal"])


@router.get("/healthz")
async def healthz():
    return {"ok": True}


@router.get("/readyz")
async def readyz():
    await pool().fetchval("select 1")
    return {"ok": True, "queues": await queue.depth()}


@router.post("/v1/internal/sarvam/callback")
async def sarvam_callback(request: Request, token: str = ""):
    expected = get_settings().sarvam_callback_token
    supplied = token or request.headers.get("x-sarvam-job-callback-token", "") or request.headers.get("authorization", "").removeprefix("Bearer ")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "bad token")
    body = await request.json()
    job_id = body.get("job_id")
    if not job_id:
        raise HTTPException(422, "job_id missing")
    row = await pool().fetchrow("select user_id from echo.stt_jobs where provider_job_id = $1", job_id)
    if row:
        await queue.send(queue.STT_BATCH_COLLECT, {"job_id": job_id, "user_id": str(row["user_id"]), "polls": 0})
    return {"ok": True}
