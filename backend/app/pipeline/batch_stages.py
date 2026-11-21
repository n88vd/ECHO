"""Accurate path: Sarvam Batch STT with diarization for pinned conversations."""

import asyncio

import numpy as np

from app.audio.decode import TARGET_SR, decode, to_wav
from app.audio.models import speaker_embedding
from app.core import costs, queue
from app.core.config import get_settings
from app.core.db import pool, vec
from app.core.storage import storage
from app.pipeline.common import Retry, keyterms, language_prior
from app.pipeline.events import stage_event
from app.pipeline.text_qa import assess, redact
from app.providers import stt

GAP_S = 0.6
MAX_POLLS = 240


async def _conversation_audio(conversation_id: str) -> tuple[np.ndarray, list[dict]]:
    segs = await pool().fetch(
        """select id, storage_path, duration_ms, snr_db, media_flag from echo.audio_segments
           where conversation_id = $1 and status = 'transcript_ok' and storage_path is not null and audio_deleted_at is null
           order by started_at""",
        conversation_id,
    )
    parts, offsets, cursor = [], [], 0
    gap = np.zeros(int(GAP_S * TARGET_SR), dtype=np.float32)
    for sg in segs:
        samples = await asyncio.to_thread(decode, await storage().download(sg["storage_path"]))
        offsets.append({"segment_id": str(sg["id"]), "start": cursor, "len": len(samples), "snr": sg["snr_db"], "media": sg["media_flag"]})
        parts += [samples, gap]
        cursor += len(samples) + len(gap)
    return (np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)), offsets


async def run_batch_submit(conversation_id: str, attempt: int = 1) -> None:
    s = get_settings()
    conv = await pool().fetchrow("select id, user_id from echo.conversations where id = $1", conversation_id)
    if conv is None:
        return
    uid = str(conv["user_id"])
    existing = await pool().fetchval(
        "select id from echo.stt_jobs where conversation_id = $1 and state in ('submitted','running','completed')", conversation_id
    )
    if existing:
        return
    async with stage_event("stt_batch_submit", "conversation", conversation_id, uid, attempt) as meta:
        audio, offsets = await _conversation_audio(conversation_id)
        seconds = len(audio) / TARGET_SR
        if seconds < 1:
            await pool().execute(
                "insert into echo.stt_jobs(user_id, conversation_id, state, error) values ($1,$2,'failed','no audio')", conv["user_id"], conversation_id
            )
            await queue.send(queue.UNDERSTAND, {"conversation_id": conversation_id, "user_id": uid})
            meta["_status"] = "skipped"
            return
        if not await costs.sarvam_budget_ok(costs.estimate_inr("sarvam_stt_batch", seconds, "audio_seconds")):
            raise Retry(1800, "sarvam budget")
        lang = await language_prior(uid) or "unknown"
        callback = f"{s.public_base_url.rstrip('/')}/v1/internal/sarvam/callback?token={s.sarvam_callback_token}" if s.sarvam_callback_token else None
        job_id = await stt().submit_batch([("conversation.wav", to_wav(audio))], lang, await keyterms(uid), callback)
        await pool().execute(
            """insert into echo.stt_jobs(user_id, conversation_id, provider_job_id, state, params, submitted_at)
               values ($1,$2,$3,'submitted',$4,now())""",
            conv["user_id"], conversation_id, job_id, {"offsets": offsets, "language": lang, "seconds": seconds},
        )
        await costs.record("sarvam_stt_batch", seconds, "audio_seconds", uid, conversation_id)
        await queue.send(queue.STT_BATCH_COLLECT, {"job_id": job_id, "user_id": uid, "polls": 0}, delay_s=20)
        meta.update(job_id=job_id, seconds=round(seconds, 1))


async def run_batch_collect(job_id: str, polls: int = 0, attempt: int = 1) -> None:
    job = await pool().fetchrow("select * from echo.stt_jobs where provider_job_id = $1", job_id)
    if job is None or job["state"] in ("completed", "failed"):
        return
    uid = str(job["user_id"])
    conversation_id = str(job["conversation_id"])
    status = await stt().batch_status(job_id)
    if status.state.lower() in ("accepted", "pending", "running"):
        if polls >= MAX_POLLS:
            await pool().execute("update echo.stt_jobs set state='failed', error='timeout' where id=$1", job["id"])
            await queue.send(queue.UNDERSTAND, {"conversation_id": conversation_id, "user_id": uid})
            return
        await pool().execute("update echo.stt_jobs set state='running' where id=$1", job["id"])
        await queue.send(queue.STT_BATCH_COLLECT, {"job_id": job_id, "user_id": uid, "polls": polls + 1}, delay_s=30)
        return
    async with stage_event("stt_batch_collect", "conversation", conversation_id, uid, attempt) as meta:
        if status.state.lower() != "completed" or not status.outputs:
            await pool().execute("update echo.stt_jobs set state='failed', error=$2, completed_at=now() where id=$1", job["id"], status.error or status.state)
            await queue.send(queue.UNDERSTAND, {"conversation_id": conversation_id, "user_id": uid})
            meta["_status"] = "skipped"
            return
        results = await stt().batch_results(job_id, list(status.outputs.values()))
        res = next(iter(results.values()))
        offsets = job["params"]["offsets"]
        audio, _ = await _conversation_audio(conversation_id)
        rows = []
        for c in res.chunks:
            a = int(c.start_s * TARGET_SR)
            seg = next((o for o in offsets if o["start"] <= a < o["start"] + o["len"] + int(GAP_S * TARGET_SR)), None)
            if seg is None:
                continue
            start_ms = int((a - seg["start"]) / TARGET_SR * 1000)
            end_ms = max(start_ms + 300, int((int(c.end_s * TARGET_SR) - seg["start"]) / TARGET_SR * 1000))
            q = assess(c.text, (end_ms - start_ms) / 1000, res.language_prob, seg["snr"], seg["media"])
            if q.score < 0.3:
                continue
            emb = await asyncio.to_thread(speaker_embedding, audio[a : int(c.end_s * TARGET_SR)]) if len(audio) else None
            rows.append((seg["segment_id"], start_ms, end_ms, redact(c.text)[0], q.score, c.speaker, emb))
        async with pool().acquire() as conn, conn.transaction():
            if rows:
                await conn.execute("delete from echo.utterances where conversation_id = $1", conversation_id)
                await conn.executemany(
                    """insert into echo.utterances(user_id, conversation_id, segment_id, start_ms, end_ms, text_native, language,
                       lang_prob, quality_score, is_provisional, stt_path, batch_speaker, speaker_embedding)
                       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,false,'batch',$10,$11::extensions.vector)""",
                    [
                        (job["user_id"], conversation_id, sg, a, b, t, res.language_code, res.language_prob, qs, spk, vec(e))
                        for sg, a, b, t, qs, spk, e in rows
                    ],
                )
            await conn.execute("update echo.stt_jobs set state='completed', completed_at=now() where id=$1", job["id"])
            await queue.send(queue.UNDERSTAND, {"conversation_id": conversation_id, "user_id": uid}, conn=conn)
        meta.update(utterances=len(rows), speakers=len({r[5] for r in rows}))
