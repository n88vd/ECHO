"""Scheduled intelligence: daily digests, Home/Work place labelling, stuck-work sweeper."""

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core import costs, queue
from app.core.db import pool
from app.pipeline.places import label_home_work
from app.prompts.text import DIGEST_SYSTEM
from app.providers import llm

logger = logging.getLogger("echo.proactive")


async def due_digests() -> list[tuple[str, str]]:
    rows = await pool().fetch(
        """select p.user_id, p.timezone, s.daily_digest_time from echo.profiles p join echo.user_settings s using (user_id)"""
    )
    out = []
    for r in rows:
        try:
            tz = ZoneInfo(r["timezone"])
        except Exception:
            tz = ZoneInfo("Asia/Kolkata")
        now = datetime.now(tz)
        if now.time() < r["daily_digest_time"]:
            continue
        exists = await pool().fetchval(
            "select 1 from echo.digests where user_id = $1 and day = $2", r["user_id"], now.date()
        )
        if not exists:
            out.append((str(r["user_id"]), now.date().isoformat()))
    return out


async def run_digest(user_id: str, day: str) -> None:
    d = datetime.fromisoformat(day).date()
    tzname = await pool().fetchval("select timezone from echo.profiles where user_id = $1", user_id)
    tz = ZoneInfo(tzname or "Asia/Kolkata")
    start = datetime.combine(d, datetime.min.time(), tz)
    mems = await pool().fetch(
        """select id, type, content_en, importance from echo.memories
           where user_id = $1 and captured_at >= $2 and captured_at < $3 and deleted_at is null
             and not (sensitivity && array['health','financial','credential'])
           order by importance desc, captured_at limit 40""",
        user_id, start, start + timedelta(days=1),
    )
    open_c = await pool().fetch(
        """select m.id, m.content_en from echo.commitments c join echo.memories m on m.id = c.memory_id
           where c.user_id = $1 and c.status = 'open' order by c.due_at nulls last limit 10""",
        user_id,
    )
    if not mems:
        await pool().execute(
            "insert into echo.digests(user_id, day, content) values ($1, $2, $3) on conflict do nothing",
            user_id, d, "No new memories today.",
        )
        return
    payload = {
        "day": day,
        "memories": [{"id": str(m["id"]), "type": m["type"], "content": m["content_en"]} for m in mems],
        "open_commitments": [{"id": str(c["id"]), "content": c["content_en"]} for c in open_c],
    }
    text, tokens = await llm().text(DIGEST_SYSTEM, json.dumps(payload, ensure_ascii=False), tier="fast", max_tokens=700)
    await costs.record("azure_llm", tokens, "tokens", user_id)
    ids = {str(m["id"]) for m in mems} | {str(c["id"]) for c in open_c}
    cites = [i for i in ids if f"m:{i}" in text]
    async with pool().acquire() as conn, conn.transaction():
        inserted = await conn.fetchval(
            """insert into echo.digests(user_id, day, content, citations) values ($1,$2,$3,$4)
               on conflict (user_id, day) do nothing returning id""",
            user_id, d, text, cites,
        )
        if inserted:
            await conn.execute(
                """insert into echo.reminders(user_id, kind, title, body, fire_at) values ($1, 'digest', 'Your day with ECHO', $2, now())""",
                user_id, text[:300],
            )


async def label_places() -> int:
    rows = await pool().fetch(
        """select c.place_id, c.user_id, c.started_at, p.timezone
           from echo.conversations c join echo.profiles p using (user_id)
           join echo.entities e on e.id = c.place_id
           where c.place_id is not null and coalesce((e.attributes->>'auto')::boolean, false)
             and c.started_at > now() - interval '30 days'"""
    )
    visits: dict[str, list] = {}
    for r in rows:
        local = r["started_at"].astimezone(ZoneInfo(r["timezone"] or "Asia/Kolkata"))
        visits.setdefault(str(r["place_id"]), []).append((local.hour, local.weekday(), True))
    n = 0
    for pid, v in visits.items():
        label = label_home_work(v)
        if label:
            await pool().execute(
                """update echo.entities set canonical_name = $2,
                   aliases = (select array(select distinct unnest(aliases || array[canonical_name, $2]))),
                   attributes = attributes || '{"auto_label": true}'
                   where id = $1 and canonical_name <> $2""",
                pid, label,
            )
            n += 1
    return n


async def sweep_stuck() -> int:
    n = 0
    for r in await pool().fetch(
        """select id, user_id, status from echo.audio_segments
           where status in ('received','audio_ok','failed_retryable') and updated_at < now() - interval '15 minutes' limit 200"""
    ):
        q = queue.AUDIO_QA if r["status"] in ("received", "failed_retryable") else queue.STT_FAST
        if r["status"] == "failed_retryable":
            await pool().execute("update echo.audio_segments set status='received' where id=$1", r["id"])
        else:
            await pool().execute("update echo.audio_segments set updated_at=now() where id=$1", r["id"])
        await queue.send(q, {"segment_id": str(r["id"]), "user_id": str(r["user_id"])})
        n += 1
    for r in await pool().fetch(
        """select id, user_id from echo.conversations where status = 'closed' and updated_at < now() - interval '20 minutes' limit 100"""
    ):
        await pool().execute("update echo.conversations set updated_at = now() where id = $1", r["id"])
        await queue.send(queue.UNDERSTAND, {"conversation_id": str(r["id"]), "user_id": str(r["user_id"])})
        n += 1
    return n
