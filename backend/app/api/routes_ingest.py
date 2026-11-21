import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import CurrentUser, CurrentUserDep
from app.api.schemas import DeviceIn, RememberIn, SegmentMeta
from app.core import queue
from app.core.db import pool, user_conn
from app.core.storage import storage
from app.pipeline.common import segment_path

router = APIRouter(prefix="/v1", tags=["ingest"])
MAX_BYTES = 5 * 1024 * 1024


@router.post("/devices")
async def register_device(body: DeviceIn, user: CurrentUser = CurrentUserDep):
    did = await pool().fetchval(
        """insert into echo.devices(id, user_id, model, os_version, app_version, last_sync_at)
           values (coalesce($1, gen_random_uuid()), $2, $3, $4, $5, now())
           on conflict (id) do update set model = excluded.model, os_version = excluded.os_version,
             app_version = excluded.app_version, last_sync_at = now()
           where echo.devices.user_id = excluded.user_id
           returning id""",
        body.device_id, user.id, body.model, body.os_version, body.app_version,
    )
    if did is None:
        raise HTTPException(409, "device belongs to another user")
    return {"device_id": str(did)}


async def _upsert_segment(user_id: str, m: SegmentMeta) -> tuple[str, str]:
    ext = "wav" if m.content_type == "audio/wav" else "ogg"
    path = segment_path(user_id, m.started_at.astimezone(UTC), str(m.segment_id), ext)
    row = await pool().fetchrow(
        """insert into echo.audio_segments(id, user_id, device_id, session_hint, storage_path, sha256, started_at, duration_ms,
             source, sample_rate, device_speech_ratio, pinned, lat, lng, accuracy_m, locality)
           values ($1,$2,(select id from echo.devices where id = $3 and user_id = $2),$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
           on conflict (id) do update set updated_at = now() where echo.audio_segments.user_id = excluded.user_id
           returning status, storage_path""",
        m.segment_id, user_id, m.device_id, m.session_hint, path, m.sha256, m.started_at, m.duration_ms, m.source,
        m.sample_rate, m.speech_ratio, m.pinned, m.lat, m.lng, m.accuracy_m, m.locality,
    )
    if row is None:
        raise HTTPException(409, "segment id conflict")
    return row["status"], row["storage_path"]


async def _mark_received(user_id: str, segment_id: str, size: int | None) -> None:
    async with pool().acquire() as conn, conn.transaction():
        updated = await conn.fetchval(
            """update echo.audio_segments set status = 'received', size_bytes = $3, received_at = now()
               where id = $1 and user_id = $2 and status = 'pending_upload' returning id""",
            segment_id, user_id, size,
        )
        if updated:
            await queue.send(queue.AUDIO_QA, {"segment_id": segment_id, "user_id": user_id}, conn=conn)


@router.post("/segments/init")
async def init_segment(meta: SegmentMeta, user: CurrentUser = CurrentUserDep):
    status, path = await _upsert_segment(user.id, meta)
    if status != "pending_upload":
        return {"segment_id": str(meta.segment_id), "status": status, "upload_url": None}
    return {"segment_id": str(meta.segment_id), "status": status, "path": path,
            "upload_url": await storage().signed_upload_url(path)}


@router.post("/segments/{segment_id}/commit")
async def commit_segment(segment_id: str, user: CurrentUser = CurrentUserDep):
    row = await pool().fetchrow(
        "select status, storage_path from echo.audio_segments where id = $1 and user_id = $2", segment_id, user.id
    )
    if row is None:
        raise HTTPException(404, "unknown segment")
    if row["status"] == "pending_upload":
        info = await storage().info(row["storage_path"])
        if info is None:
            raise HTTPException(409, "object not uploaded yet")
        await _mark_received(user.id, segment_id, info.get("size") or (info.get("metadata") or {}).get("size"))
    return {"segment_id": segment_id, "status": "received" if row["status"] == "pending_upload" else row["status"]}


@router.post("/segments")
async def upload_segment(meta: str = Form(...), file: UploadFile = File(...), user: CurrentUser = CurrentUserDep):
    """Single-call upload: multipart `meta` (JSON SegmentMeta) + `file`. Idempotent on segment_id."""
    m = SegmentMeta.model_validate_json(meta)
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "segment too large")
    if hashlib.sha256(data).hexdigest() != m.sha256:
        raise HTTPException(422, "sha256 mismatch")
    status, path = await _upsert_segment(user.id, m)
    if status == "pending_upload":
        await storage().upload(path, data, m.content_type)
        await _mark_received(user.id, str(m.segment_id), len(data))
        status = "received"
    return {"segment_id": str(m.segment_id), "status": status}


@router.post("/remember")
async def remember(body: RememberIn, user: CurrentUser = CurrentUserDep):
    at = body.at or datetime.now(UTC)
    lo, hi = at - timedelta(seconds=body.before_s), at + timedelta(seconds=body.after_s)
    async with pool().acquire() as conn, conn.transaction():
        segs = await conn.fetch(
            """update echo.audio_segments set pinned = true
               where user_id = $1 and started_at + duration_ms * interval '1 millisecond' >= $2 and started_at <= $3
               returning conversation_id""",
            user.id, lo, hi,
        )
        conv_ids = list({r["conversation_id"] for r in segs if r["conversation_id"]})
        if conv_ids:
            await conn.execute(
                "update echo.conversations set pinned = true where id = any($1::uuid[]) and user_id = $2", conv_ids, user.id
            )
            await conn.execute(
                "update echo.memories set pinned = true, importance = greatest(importance, 0.9) where conversation_id = any($1::uuid[])",
                conv_ids,
            )
    return {"pinned_segments": len(segs), "window": {"from": lo.isoformat(), "to": hi.isoformat()}}


@router.get("/status")
async def status(user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        today = await conn.fetchrow(
            "select speech_seconds, asks from echo.usage_daily where user_id = $1 and day = current_date", user.id
        )
        pending = await conn.fetchval(
            """select count(*) from echo.audio_segments where user_id = $1
               and status in ('pending_upload','received','audio_ok','failed_retryable')""",
            user.id,
        )
        last = await conn.fetchval("select max(received_at) from echo.audio_segments where user_id = $1", user.id)
        processing = await conn.fetchval(
            "select count(*) from echo.conversations where user_id = $1 and status in ('open','closed')", user.id
        )
        counts = await conn.fetchrow(
            """select (select count(*) from echo.memories where user_id = $1 and deleted_at is null) as memories,
                      (select count(*) from echo.commitments where user_id = $1 and status = 'open') as open_commitments,
                      (select count(*) from echo.entities where user_id = $1 and kind = 'person') as people""",
            user.id,
        )
        has_vp = await conn.fetchval("select exists(select 1 from echo.voiceprints where user_id = $1)", user.id)
    return {
        "speech_minutes_today": round((today["speech_seconds"] if today else 0) / 60, 1),
        "asks_today": today["asks"] if today else 0,
        "segments_pending": pending,
        "conversations_processing": processing,
        "last_upload_at": last.isoformat() if last else None,
        "memories": counts["memories"],
        "open_commitments": counts["open_commitments"],
        "people": counts["people"],
        "voice_enrolled": has_vp,
        "server_time": datetime.now(UTC).isoformat(),
    }


@router.get("/sync")
async def sync(since: datetime | None = None, device_id: str | None = None, user: CurrentUser = CurrentUserDep):
    since = since or datetime.now(UTC) - timedelta(days=7)
    async with user_conn(user.id) as conn:
        reminders = await conn.fetch(
            """select id, kind, title, body, fire_at, status, commitment_id, updated_at from echo.reminders
               where user_id = $1 and updated_at > $2 order by updated_at limit 500""",
            user.id, since,
        )
        digest = await conn.fetchrow(
            "select id, day, created_at from echo.digests where user_id = $1 order by day desc limit 1", user.id
        )
    if device_id:
        await pool().execute(
            "update echo.devices set last_sync_at = now() where id = $1 and user_id = $2", device_id, user.id
        )
    cursor = max([r["updated_at"] for r in reminders], default=since)
    return {
        "cursor": cursor.isoformat(),
        "server_time": datetime.now(UTC).isoformat(),
        "reminders": [
            {"id": str(r["id"]), "kind": r["kind"], "title": r["title"], "body": r["body"], "fire_at": r["fire_at"].isoformat(),
             "status": r["status"], "commitment_id": str(r["commitment_id"]) if r["commitment_id"] else None}
            for r in reminders
        ],
        "latest_digest": {"id": str(digest["id"]), "day": digest["day"].isoformat()} if digest else None,
    }


@router.post("/reminders/{reminder_id}/delivered")
async def reminder_delivered(reminder_id: str, user: CurrentUser = CurrentUserDep):
    await pool().execute(
        """update echo.reminders set status = 'delivered', delivered_at = now()
           where id = $1 and user_id = $2 and status = 'scheduled'""",
        reminder_id, user.id,
    )
    return {"ok": True}
