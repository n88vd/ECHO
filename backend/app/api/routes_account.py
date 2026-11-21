import asyncio
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, CurrentUserDep
from app.api.schemas import SettingsPatch
from app.audio.decode import TARGET_SR, AudioDecodeError, decode
from app.audio.models import speaker_embedding, vad_segments
from app.core.db import pool, user_conn, vec
from app.core.storage import storage

router = APIRouter(prefix="/v1", tags=["account"])


@router.get("/settings")
async def get_settings_(user: CurrentUser = CurrentUserDep):
    async with user_conn(user.id) as conn:
        s = await conn.fetchrow("select * from echo.user_settings where user_id = $1", user.id)
        p = await conn.fetchrow("select * from echo.profiles where user_id = $1", user.id)
    return {
        "display_name": p["display_name"], "timezone": p["timezone"], "answer_language": p["answer_language"],
        "audio_retention_days": s["audio_retention_days"], "retention_forever": s["audio_retention_days"] is None,
        "quiet_hours": s["quiet_hours"], "earbud_policy": s["earbud_policy"], "location_enabled": s["location_enabled"],
        "daily_digest_time": s["daily_digest_time"].strftime("%H:%M"), "speech_cap_min_per_day": s["speech_cap_min_per_day"],
        "email": user.email,
    }


@router.patch("/settings")
async def patch_settings(body: SettingsPatch, user: CurrentUser = CurrentUserDep):
    if body.timezone:
        try:
            ZoneInfo(body.timezone)
        except Exception as e:
            raise HTTPException(422, "invalid timezone") from e
    async with user_conn(user.id) as conn:
        if body.retention_forever:
            await conn.execute("update echo.user_settings set audio_retention_days = null where user_id = $1", user.id)
        elif body.audio_retention_days is not None:
            await conn.execute("update echo.user_settings set audio_retention_days = $2 where user_id = $1", user.id, body.audio_retention_days)
        await conn.execute(
            """update echo.user_settings set quiet_hours = coalesce($2, quiet_hours), earbud_policy = coalesce($3, earbud_policy),
               location_enabled = coalesce($4, location_enabled), daily_digest_time = coalesce($5, daily_digest_time),
               speech_cap_min_per_day = coalesce($6, speech_cap_min_per_day) where user_id = $1""",
            user.id, body.quiet_hours, body.earbud_policy, body.location_enabled, body.daily_digest_time, body.speech_cap_min_per_day,
        )
        await conn.execute(
            """update echo.profiles set display_name = coalesce($2, display_name), timezone = coalesce($3, timezone),
               answer_language = coalesce($4, answer_language) where user_id = $1""",
            user.id, body.display_name, body.timezone, body.answer_language,
        )
        if body.location_enabled is False:
            await pool().execute(
                "update echo.audio_segments set lat = null, lng = null, accuracy_m = null, locality = null where user_id = $1", user.id
            )
    return await get_settings_(user)


@router.post("/voiceprint")
async def enroll_voice(file: UploadFile = File(...), user: CurrentUser = CurrentUserDep):
    data = await file.read(10 * 1024 * 1024)
    try:
        samples = await asyncio.to_thread(decode, data)
    except AudioDecodeError as e:
        raise HTTPException(422, "unsupported audio") from e
    regions = await asyncio.to_thread(vad_segments, samples)
    speech = np.concatenate([samples[s:e] for s, e in regions]) if regions else samples[:0]
    if len(speech) < 8 * TARGET_SR:
        raise HTTPException(422, f"need at least 8 s of clear speech, got {len(speech) / TARGET_SR:.1f} s")
    emb = await asyncio.to_thread(speaker_embedding, speech)
    if emb is None:
        raise HTTPException(422, "could not extract voiceprint")
    await pool().execute(
        """insert into echo.voiceprints(user_id, embedding, model) values ($1, $2::extensions.vector, 'campplus_en_voxceleb')
           on conflict (user_id) do update set embedding = excluded.embedding, model = excluded.model, created_at = now()""",
        user.id, vec(emb),
    )
    await pool().execute("update echo.profiles set onboarded_at = coalesce(onboarded_at, now()) where user_id = $1", user.id)
    return {"enrolled": True, "speech_seconds": round(len(speech) / TARGET_SR, 1)}


@router.delete("/voiceprint")
async def delete_voice(user: CurrentUser = CurrentUserDep):
    await pool().execute("delete from echo.voiceprints where user_id = $1", user.id)
    return {"deleted": True}


EXPORT_TABLES = [
    ("profile", "select * from echo.profiles where user_id = $1"),
    ("settings", "select * from echo.user_settings where user_id = $1"),
    ("conversations", "select id, started_at, ended_at, title_en, summary_en, languages, place_id, pinned from echo.conversations where user_id = $1 order by started_at"),
    ("utterances", "select id, conversation_id, start_ms, end_ms, text_native, text_en, language, speaker_id from echo.utterances where user_id = $1 order by created_at"),
    ("speakers", "select id, conversation_id, label, is_user, person_id from echo.speakers where user_id = $1"),
    ("memories", "select id, conversation_id, type, content_en, content_native, importance, captured_at, time_start, time_end, superseded_by, pinned from echo.memories where user_id = $1 and deleted_at is null order by captured_at"),
    ("memory_evidence", "select memory_id, utterance_id from echo.memory_evidence where user_id = $1"),
    ("entities", "select id, kind, canonical_name, aliases, lat, lng from echo.entities where user_id = $1"),
    ("memory_entities", "select memory_id, entity_id, role from echo.memory_entities where user_id = $1"),
    ("commitments", "select * from echo.commitments where user_id = $1"),
    ("reminders", "select id, kind, title, body, fire_at, status from echo.reminders where user_id = $1"),
    ("digests", "select day, content from echo.digests where user_id = $1"),
    ("audio_segments", "select id, started_at, duration_ms, source, status, lat, lng, locality, storage_path, audio_deleted_at from echo.audio_segments where user_id = $1"),
    ("ask_log", "select created_at, query_native, answer_text from echo.ask_log where user_id = $1"),
]


@router.get("/export")
async def export(user: CurrentUser = CurrentUserDep):
    async def gen():
        yield '{"exported_at": ' + json.dumps(datetime.now(UTC).isoformat()) + ', "user_id": ' + json.dumps(user.id)
        async with user_conn(user.id) as conn:
            for name, sql in EXPORT_TABLES:
                rows = await conn.fetch(sql, user.id)
                data = [{k: (v if not hasattr(v, "isoformat") else v.isoformat()) for k, v in dict(r).items()} for r in rows]
                yield f', "{name}": ' + json.dumps(data, default=str, ensure_ascii=False)
        yield "}"

    return StreamingResponse(gen(), media_type="application/json",
                             headers={"Content-Disposition": 'attachment; filename="echo-export.json"'})


@router.delete("/account")
async def delete_account(user: CurrentUser = CurrentUserDep):
    """Deletes all ECHO data (audio, transcripts, memories). The shared Supabase auth identity is left intact."""
    paths = await storage().list_prefix(user.id)
    if paths:
        await storage().delete(paths)
    await pool().execute("delete from echo.profiles where user_id = $1", user.id)
    from app.core import auth

    auth._known_profiles.discard(user.id)
    return {"deleted": True, "files": len(paths)}
