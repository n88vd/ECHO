import asyncio
import hashlib
import logging
from datetime import timedelta

from app.audio.decode import TARGET_SR, AudioDecodeError, decode, to_wav
from app.audio.models import speaker_embedding
from app.audio.qa import analyze, decide
from app.core import costs, queue
from app.core.config import get_settings
from app.core.db import pool, vec
from app.core.storage import storage
from app.pipeline.common import (
    Retry,
    compact_speech,
    keyterms,
    language_prior,
    map_ms,
    next_ist_midnight_delay,
)
from app.pipeline.events import stage_event
from app.pipeline.text_qa import assess, has_remember_trigger, redact
from app.providers import stt

logger = logging.getLogger("echo.ingest")


async def run_audio_qa(segment_id: str, attempt: int = 1) -> None:
    s = get_settings()
    seg = await pool().fetchrow("select * from echo.audio_segments where id = $1", segment_id)
    if seg is None or seg["status"] not in ("received", "failed_retryable"):
        return
    uid = str(seg["user_id"])
    async with stage_event("audio_qa", "segment", segment_id, uid, attempt) as meta:
        data = await storage().download(seg["storage_path"])
        if hashlib.sha256(data).hexdigest() != seg["sha256"]:
            await pool().execute(
                "update echo.audio_segments set status='discarded_blank', qa_reason='checksum_mismatch' where id=$1", segment_id
            )
            await storage().delete([seg["storage_path"]])
            meta["_status"] = "skipped"
            return
        try:
            samples = await asyncio.to_thread(decode, data)
        except AudioDecodeError as e:
            await pool().execute(
                "update echo.audio_segments set status='discarded_blank', qa_reason='decode_error', error=$2 where id=$1",
                segment_id, str(e)[:500],
            )
            await storage().delete([seg["storage_path"]])
            meta["_status"] = "skipped"
            return
        f = await asyncio.to_thread(analyze, samples)
        d = decide(f, s.min_speech_ms, s.min_speech_ratio, s.min_rms_dbfs)
        meta.update(f.dict(), reason=d.reason)
        common = (segment_id, f.snr_db, f.speech_ms, f.speech_ratio, f.rms_dbfs, f.clipping_ratio, f.media_suspect, d.reason)
        if not d.keep:
            await pool().execute(
                """update echo.audio_segments set status='discarded_blank', snr_db=$2, speech_ms=$3, speech_ratio=$4,
                   rms_dbfs=$5, clipping_ratio=$6, media_flag=$7, qa_reason=$8, audio_deleted_at=now() where id=$1""",
                *common,
            )
            await storage().delete([seg["storage_path"]])
            return

        if f.speech_ratio < 0.7 and f.speech_regions:
            wav, speech_map = compact_speech(samples, f.speech_regions)
        else:
            wav, speech_map = to_wav(samples), None
        speech_path = seg["storage_path"].rsplit(".", 1)[0] + ".speech.wav"
        await storage().upload(speech_path, wav, "audio/wav")

        seg_end = seg["started_at"] + timedelta(milliseconds=seg["duration_ms"])
        gap = timedelta(seconds=s.conversation_gap_s)
        async with pool().acquire() as conn, conn.transaction():
            await conn.execute("select pg_advisory_xact_lock(hashtext($1))", uid)
            conv_id = await conn.fetchval(
                """select id from echo.conversations
                   where user_id = $1 and status = 'open'
                     and (($2::uuid is not null and session_hint = $2)
                          or ($3::timestamptz between started_at - $4::interval and last_segment_at + $4::interval))
                   order by last_segment_at desc limit 1""",
                seg["user_id"], seg["session_hint"], seg["started_at"], gap,
            )
            if conv_id is None:
                conv_id = await conn.fetchval(
                    """insert into echo.conversations(user_id, session_hint, started_at, last_segment_at, pinned)
                       values ($1, $2, $3, $4, $5) returning id""",
                    seg["user_id"], seg["session_hint"], seg["started_at"], seg_end, seg["pinned"],
                )
            else:
                await conn.execute(
                    """update echo.conversations set started_at = least(started_at, $2),
                       last_segment_at = greatest(last_segment_at, $3), pinned = pinned or $4, last_activity_at = now()
                       where id = $1""",
                    conv_id, seg["started_at"], seg_end, seg["pinned"],
                )
            await conn.execute(
                """update echo.audio_segments set status='audio_ok', snr_db=$2, speech_ms=$3, speech_ratio=$4,
                   rms_dbfs=$5, clipping_ratio=$6, media_flag=$7, qa_reason=$8, conversation_id=$9,
                   speech_path=$10, speech_map=$11 where id=$1""",
                *common, conv_id, speech_path, speech_map,
            )
            await queue.send(queue.STT_FAST, {"segment_id": segment_id, "user_id": uid}, conn=conn)
        meta["conversation_id"] = str(conv_id)


async def run_stt_fast(segment_id: str, attempt: int = 1) -> None:
    s = get_settings()
    seg = await pool().fetchrow("select * from echo.audio_segments where id = $1", segment_id)
    if seg is None or seg["status"] != "audio_ok":
        return
    uid = str(seg["user_id"])
    seconds = max(1, (seg["speech_ms"] or seg["duration_ms"]) // 1000)
    if not await costs.speech_cap_ok(uid, seconds):
        raise Retry(next_ist_midnight_delay(), "user daily speech cap reached")
    if not await costs.sarvam_budget_ok(costs.estimate_inr("sarvam_stt", seconds, "audio_seconds")):
        raise Retry(1800, "global sarvam budget reached")

    async with stage_event("stt_fast", "segment", segment_id, uid, attempt) as meta:
        original = await storage().download(seg["storage_path"])
        send_path = seg["speech_path"] or seg["storage_path"]
        payload = original if send_path == seg["storage_path"] else await storage().download(send_path)
        fname = send_path.rsplit("/", 1)[-1]
        terms = await keyterms(uid)
        res = await stt().transcribe(payload, fname, "unknown", terms)
        billed = seconds
        prior = await language_prior(uid)
        if (
            res.language_prob is not None
            and res.language_prob < s.lang_prob_retry_below
            and prior
            and prior != res.language_code
        ):
            alt = await stt().transcribe(payload, fname, prior, terms)
            billed += seconds
            if alt.transcript:
                alt.language_code = alt.language_code or prior
                res = alt
                meta["language_retry"] = prior
        await costs.record("sarvam_stt", billed, "audio_seconds", uid, segment_id)
        await costs.add_speech_seconds(uid, seconds)

        samples = await asyncio.to_thread(decode, original)
        seg_dur_s = seg["duration_ms"] / 1000
        rows, trigger = [], False
        chunks = res.chunks or []
        for c in chunks:
            start_ms = map_ms(c.start_s * 1000, seg["speech_map"])
            end_ms = map_ms(c.end_s * 1000, seg["speech_map"]) if c.end_s > c.start_s else int(seg_dur_s * 1000)
            if end_ms <= start_ms:
                end_ms = min(int(seg_dur_s * 1000), start_ms + 1000)
            q = assess(c.text, (end_ms - start_ms) / 1000, res.language_prob, seg["snr_db"], seg["media_flag"])
            if q.score < 0.3:
                continue
            trigger = trigger or has_remember_trigger(c.text)
            text, _ = redact(c.text)
            emb = await asyncio.to_thread(
                speaker_embedding, samples[int(start_ms / 1000 * TARGET_SR) : int(end_ms / 1000 * TARGET_SR)]
            )
            rows.append((start_ms, end_ms, text, q.score, emb))
        meta.update(language=res.language_code, lang_prob=res.language_prob, chunks=len(chunks), kept=len(rows))

        async with pool().acquire() as conn, conn.transaction():
            if not rows:
                await conn.execute(
                    "update echo.audio_segments set status='discarded_noise', qa_reason='no_valuable_text' where id=$1",
                    segment_id,
                )
                return
            await conn.execute("delete from echo.utterances where segment_id = $1 and stt_path = 'fast'", segment_id)
            await conn.executemany(
                """insert into echo.utterances(user_id, conversation_id, segment_id, start_ms, end_ms, text_native,
                   language, lang_prob, quality_score, is_provisional, stt_path, stt_request_id, speaker_embedding)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9,true,'fast',$10,$11::extensions.vector)""",
                [
                    (seg["user_id"], seg["conversation_id"], segment_id, a, b, t, res.language_code, res.language_prob, qs,
                     res.request_id, vec(e))
                    for a, b, t, qs, e in rows
                ],
            )
            await conn.execute(
                "update echo.audio_segments set status='transcript_ok', pinned = pinned or $2 where id=$1",
                segment_id, trigger,
            )
            await conn.execute(
                """update echo.conversations set last_activity_at = now(), pinned = pinned or $2,
                   languages = (select array(select distinct unnest(languages || $3::text[])))
                   where id=$1""",
                seg["conversation_id"], trigger, [res.language_code] if res.language_code else [],
            )
        if trigger:
            meta["remember_this"] = True
