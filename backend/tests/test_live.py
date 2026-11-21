"""Live end-to-end: real Sarvam STT/TTS + Azure LLM/embeddings + Supabase. Opt-in: ECHO_LIVE_TESTS=1 PROVIDERS=live."""

import asyncio
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pytest

from app.audio.decode import decode, to_wav
from app.core import queue
from app.core.db import close_pool, init_pool, pool
from app.main import app
from app.workers.runtime import drain_once
from tests.helpers import create_test_user, delete_test_user

pytestmark = pytest.mark.skipif(
    os.getenv("ECHO_LIVE_TESTS") != "1" or os.getenv("PROVIDERS") != "live", reason="set ECHO_LIVE_TESTS=1 PROVIDERS=live"
)


async def _pump(uid: str, timeout_s: int = 900) -> None:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        for q in (queue.AUDIO_QA, queue.STT_FAST, queue.STT_BATCH_SUBMIT, queue.STT_BATCH_COLLECT, queue.UNDERSTAND):
            await drain_once(q, 10)
        await pool().execute(
            "update echo.conversations set last_activity_at = now() - interval '10 minutes' where user_id = $1 and status = 'open'", uid
        )
        await pool().fetchval("select echo.close_stale_conversations()")
        left = await pool().fetchval(
            "select count(*) from echo.conversations where user_id = $1 and status <> 'understood'", uid
        )
        pending = await pool().fetchval(
            "select count(*) from echo.audio_segments where user_id = $1 and status in ('received','audio_ok')", uid
        )
        if left == 0 and pending == 0:
            return
        await asyncio.sleep(5)
    raise AssertionError("pipeline did not finish in time")


async def test_live_multilingual(fixture_bytes):
    await init_pool()
    uid, token, _ = await create_test_user()
    h = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=120) as c:
            voice = decode(fixture_bytes("en_promise.ogg"))
            r = await c.post("/v1/voiceprint", headers=h, files={"file": ("e.wav", to_wav(np.concatenate([voice] * 4)), "audio/wav")})
            assert r.status_code == 200, r.text
            t0 = datetime.now(UTC) - timedelta(hours=2)
            plan = [("en_promise.ogg", t0), ("hi_passport.ogg", t0 + timedelta(minutes=20)),
                    ("ta_doctor.ogg", t0 + timedelta(minutes=40)), ("hinglish_remember.ogg", t0 + timedelta(minutes=60)),
                    ("silence.ogg", t0 + timedelta(minutes=61))]
            for name, started in plan:
                data = fixture_bytes(name)
                meta = {"segment_id": str(uuid.uuid4()), "sha256": hashlib.sha256(data).hexdigest(), "duration_ms": 6000,
                        "started_at": started.isoformat(), "lat": 12.9716, "lng": 77.5946, "locality": "Indiranagar, Bengaluru"}
                r = await c.post("/v1/segments", headers=h, data={"meta": json.dumps(meta)}, files={"file": ("a.ogg", data, "audio/ogg")})
                assert r.status_code == 200, r.text
            await _pump(uid)

            utts = await pool().fetch("select language, text_native, text_en from echo.utterances where user_id = $1", uid)
            langs = {u["language"] for u in utts}
            print("\nLANGS", langs)
            for u in utts:
                print("UTT", u["language"], "|", u["text_native"], "|", u["text_en"])
            assert {"en-IN", "hi-IN", "ta-IN"} <= langs
            assert all(u["text_en"] for u in utts)
            mems = await pool().fetch("select type, content_en, importance, pinned from echo.memories where user_id = $1", uid)
            for m in mems:
                print("MEM", m["type"], m["importance"], m["pinned"], "|", m["content_en"])
            assert {"commitment", "object_location"} <= {m["type"] for m in mems}
            jobs = await pool().fetch("select state from echo.stt_jobs where user_id = $1", uid)
            print("BATCH JOBS", [j["state"] for j in jobs])

            for q, lang in [("What did I promise Rahul?", None), ("मैंने अपना पासपोर्ट कहाँ रखा है?", None),
                            ("When do I have to see the doctor?", None), ("What did I tell Priya?", None)]:
                res = (await c.post("/v1/ask", headers=h, json={"query": q, "language": lang, "speak": q.startswith("मैंने")})).json()
                print("ASK", q, "->", res["answer_language"], "|", res["answer"], "| cites:", [x["type"] for x in res["citations"]],
                      "| tts:", bool(res.get("tts_url")), "|", res["latency_ms"], "ms", res.get("timings"))
                assert res["citations"], res
            hi = (await c.post("/v1/ask", headers=h, json={"query": "मैंने अपना पासपोर्ट कहाँ रखा है?"})).json()
            assert any("\u0900" <= ch <= "\u097f" for ch in hi["answer"]), hi
            unknown = (await c.post("/v1/ask", headers=h, json={"query": "What is my bank locker number?"})).json()
            print("UNKNOWN ->", unknown["answer"])
            await c.delete("/v1/account", headers=h)
    finally:
        await pool().execute("delete from echo.profiles where user_id = $1", uid)
        await delete_test_user(uid)
        await close_pool()
