import asyncio
import logging
import signal
import time
from collections.abc import Awaitable, Callable

from app.core import queue
from app.core.config import get_settings
from app.core.db import close_pool, init_pool, pool
from app.core.logging import log, setup_logging
from app.pipeline import proactive, purge
from app.pipeline.batch_stages import run_batch_collect, run_batch_submit
from app.pipeline.common import Retry
from app.pipeline.ingest_stages import run_audio_qa, run_stt_fast
from app.pipeline.understand import run_understand
from app.providers.base import ProviderError

logger = logging.getLogger("echo.worker")
MAX_ATTEMPTS = 6

Handler = Callable[[dict, int], Awaitable[None]]


async def _dead(q: str, body: dict, err: str) -> None:
    if body.get("segment_id"):
        await pool().execute("update echo.audio_segments set status='dead', error=$2 where id=$1", body["segment_id"], err[:1000])
    if body.get("conversation_id") and q == queue.UNDERSTAND:
        await pool().execute("update echo.conversations set status='failed' where id=$1", body["conversation_id"])
    if body.get("conversation_id") and q == queue.STT_BATCH_SUBMIT:
        await pool().execute(
            """insert into echo.stt_jobs(user_id, conversation_id, state, error)
               select user_id, id, 'failed', $2 from echo.conversations where id = $1""",
            body["conversation_id"], err[:1000],
        )
        await queue.send(queue.UNDERSTAND, {"conversation_id": body["conversation_id"], "user_id": body.get("user_id")})
    if body.get("job_id") and q == queue.STT_BATCH_COLLECT:
        row = await pool().fetchrow(
            "update echo.stt_jobs set state='failed', error=$2 where provider_job_id=$1 returning conversation_id, user_id",
            body["job_id"], err[:1000],
        )
        if row:
            await queue.send(queue.UNDERSTAND, {"conversation_id": str(row["conversation_id"]), "user_id": str(row["user_id"])})


HANDLERS: dict[str, tuple[Handler, int]] = {
    queue.AUDIO_QA: (lambda b, a: run_audio_qa(b["segment_id"], a), 120),
    queue.STT_FAST: (lambda b, a: run_stt_fast(b["segment_id"], a), 180),
    queue.STT_BATCH_SUBMIT: (lambda b, a: run_batch_submit(b["conversation_id"], a), 600),
    queue.STT_BATCH_COLLECT: (lambda b, a: run_batch_collect(b["job_id"], int(b.get("polls", 0)), a), 600),
    queue.UNDERSTAND: (lambda b, a: run_understand(b["conversation_id"], a), 600),
    queue.PROACTIVE: (lambda b, a: proactive.run_digest(b["user_id"], b["day"]), 300),
    queue.PURGE: (lambda b, a: purge.purge_conversation_audio(b["conversation_id"]), 120),
}


async def process(q: str, msg: queue.Message) -> None:
    handler, _vt = HANDLERS[q]
    try:
        await handler(msg.body, msg.read_ct)
        await queue.delete(q, msg.msg_id)
    except Retry as r:
        await queue.send(q, msg.body, delay_s=r.delay_s)
        await queue.delete(q, msg.msg_id)
        log(logger, logging.INFO, "rescheduled", queue=q, delay_s=r.delay_s, reason=str(r))
    except Exception as e:
        fatal = isinstance(e, ProviderError) and not e.retryable
        if fatal or msg.read_ct >= MAX_ATTEMPTS:
            await queue.archive(q, msg.msg_id)
            await _dead(q, msg.body, repr(e))
            log(logger, logging.ERROR, "dead-lettered", queue=q, body=msg.body, error=repr(e)[:500])
        else:
            backoff = min(1800, 10 * 2**msg.read_ct)
            await queue.set_vt(q, msg.msg_id, backoff)
            log(logger, logging.WARNING, "retry scheduled", queue=q, attempt=msg.read_ct, backoff_s=backoff, error=repr(e)[:300])


async def drain_once(q: str, qty: int | None = None) -> int:
    """Process currently visible messages once (used by tests and the consumer loop)."""
    _, vt = HANDLERS[q]
    msgs = await queue.read(q, vt, qty or get_settings().worker_concurrency)
    await asyncio.gather(*(process(q, m) for m in msgs))
    return len(msgs)


async def consumer(q: str, stop: asyncio.Event) -> None:
    idle = 1.0
    while not stop.is_set():
        try:
            n = await drain_once(q)
            idle = 0.2 if n else min(5.0, idle * 1.5)
        except Exception as e:
            log(logger, logging.ERROR, "consumer error", queue=q, error=repr(e)[:300])
            idle = 5.0
        try:
            await asyncio.wait_for(stop.wait(), timeout=idle)
        except TimeoutError:
            pass


async def scheduler(stop: asyncio.Event) -> None:
    last: dict[str, float] = {}

    def due(name: str, every: float) -> bool:
        now = time.monotonic()
        if now - last.get(name, 0) >= every:
            last[name] = now
            return True
        return False

    while not stop.is_set():
        try:
            if due("close", 60):
                await pool().fetchval("select echo.close_stale_conversations()")
            if due("sweep", 300):
                await proactive.sweep_stuck()
            if due("digests", 300):
                for uid, day in await proactive.due_digests():
                    await queue.send(queue.PROACTIVE, {"user_id": uid, "day": day})
            if due("purge", 3600):
                await purge.purge_expired()
            if due("places", 6 * 3600):
                await proactive.label_places()
        except Exception as e:
            log(logger, logging.ERROR, "scheduler error", error=repr(e)[:300])
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except TimeoutError:
            pass


async def main() -> None:
    setup_logging(get_settings().log_level)
    await init_pool()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    log(logger, logging.INFO, "worker started", queues=list(HANDLERS), providers=get_settings().providers)
    await asyncio.gather(*(consumer(q, stop) for q in HANDLERS), scheduler(stop))
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
