from dataclasses import dataclass
from typing import Any

import asyncpg

from app.core.db import pool

AUDIO_QA = "echo_audio_qa"
STT_FAST = "echo_stt_fast"
STT_BATCH_SUBMIT = "echo_stt_batch_submit"
STT_BATCH_COLLECT = "echo_stt_batch_collect"
UNDERSTAND = "echo_understand"
ENTITY_RESOLVE = "echo_entity_resolve"
EMBED = "echo_embed"
PROACTIVE = "echo_proactive"
PURGE = "echo_purge"
ALL_QUEUES = [AUDIO_QA, STT_FAST, STT_BATCH_SUBMIT, STT_BATCH_COLLECT, UNDERSTAND, ENTITY_RESOLVE, EMBED, PROACTIVE, PURGE]


@dataclass
class Message:
    msg_id: int
    read_ct: int
    body: dict[str, Any]


async def send(queue: str, body: dict[str, Any], delay_s: int = 0, conn: asyncpg.Connection | None = None) -> int:
    q = "select pgmq.send($1::text, $2::jsonb, $3::integer)"
    if conn is not None:
        return await conn.fetchval(q, queue, body, delay_s)
    return await pool().fetchval(q, queue, body, delay_s)


async def read(queue: str, vt_s: int, qty: int) -> list[Message]:
    rows = await pool().fetch("select msg_id, read_ct, message from pgmq.read($1::text, $2::integer, $3::integer)", queue, vt_s, qty)
    return [Message(r["msg_id"], r["read_ct"], r["message"]) for r in rows]


async def delete(queue: str, msg_id: int) -> None:
    await pool().execute("select pgmq.delete($1::text, $2::bigint)", queue, msg_id)


async def archive(queue: str, msg_id: int) -> None:
    await pool().execute("select pgmq.archive($1::text, $2::bigint)", queue, msg_id)


async def set_vt(queue: str, msg_id: int, vt_s: int) -> None:
    await pool().execute("select msg_id from pgmq.set_vt($1::text, $2::bigint, $3::integer)", queue, msg_id, vt_s)


async def has_pending(queue: str, key: str, value: str) -> bool:
    """True if a message with body[key] == value is waiting (visible, delayed or in flight) on the queue."""
    if queue not in ALL_QUEUES:
        raise ValueError(queue)
    return bool(await pool().fetchval(f"select exists(select 1 from pgmq.q_{queue} where message->>$1 = $2)", key, value))


async def depth() -> dict[str, int]:
    out = {}
    async with pool().acquire() as conn:
        for q in ALL_QUEUES:
            out[q] = await conn.fetchval(f"select count(*) from pgmq.q_{q} where vt <= now()")
    return out
